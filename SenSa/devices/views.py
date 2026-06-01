"""
devices/views.py — 센서 장비 CRUD + 센서 데이터 수신/저장

[변경 이력]
  ARIMA 연동 v3: ARIMA 탐지 후 evaluate_sensor 직접 호출
  IsolationForest v1: 추세 예측 + AIPrediction 기록 + 검증
  C′-3a (5차 세션): SensorData 라벨 컬럼 (scenario_id, expected_phase, expected_status)
                    POST payload 동봉 라벨 → SensorData 저장. AI 평가 ground truth.
"""
import logging
import time
from datetime import timedelta
from threading import Lock

from django.utils import timezone
from rest_framework import viewsets, status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Device, SensorData
from .serializers import DeviceSerializer
from realtime.publishers import publish_sensor_update, publish_alarm

from alerts.services import classify_gas, classify_power, evaluate_sensor
from alerts.services.anomaly_detector import detect_anomaly
from alerts.services.trend_predictor import predict_trend, verify_predictions
from alerts.services.classifiers import GAS_THRESHOLDS
from alerts.models import Alarm, AIPrediction

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# AI 예측 알람 throttle — sensor + gas 별 60초 이내 중복 알람 차단
# (CRITICAL/WARNING 즉시 알람은 evaluate_sensor 별도 경로 — 영향 없음)
# ═══════════════════════════════════════════════════════════
_AI_PRED_THROTTLE_SEC = 60.0
_ai_pred_throttle: dict[tuple[str, str], float] = {}
_ai_pred_throttle_lock = Lock()

# 가스 9종 라벨
GAS_LABELS = {
    'co':  'CO',  'h2s': 'H2S', 'co2': 'CO2', 'o2':  'O2',
    'no2': 'NO2', 'so2': 'SO2', 'o3':  'O3',  'nh3': 'NH3', 'voc': 'VOC',
}

# 가스 9종 caution 임계치 (IsolationForest 예측용)
GAS_THRESHOLDS_CAUTION = {k: v['caution'] for k, v in GAS_THRESHOLDS.items()}
GAS_THRESHOLDS_CAUTION['o2'] = 18.0  # o2는 하한 기준


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.filter(is_active=True)
    serializer_class = DeviceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        sensor_type = self.request.query_params.get('sensor_type')
        if sensor_type:
            qs = qs.filter(sensor_type=sensor_type)
        return qs


@method_decorator(csrf_exempt, name='dispatch')
class SensorDataView(APIView):

    def get(self, request):
        device_id = request.query_params.get('device_id')
        limit = int(request.query_params.get('limit', 20))
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=http_status.HTTP_404_NOT_FOUND)
        data = SensorData.objects.filter(device=device)[:limit]
        result = [{
            'timestamp': d.timestamp.strftime('%H:%M:%S'),
            'co': d.co, 'h2s': d.h2s, 'co2': d.co2, 'o2': d.o2,
            'no2': d.no2, 'so2': d.so2, 'o3': d.o3, 'nh3': d.nh3, 'voc': d.voc,
            'current': d.current, 'voltage': d.voltage, 'watt': d.watt,
            'status': d.status,
        } for d in reversed(list(data))]
        return Response({'device_id': device_id, 'data': result})

    def post(self, request):
        device_id = request.data.get('device_id')
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=http_status.HTTP_404_NOT_FOUND)

        sensor_type = request.data.get('sensor_type') or device.sensor_type

        def _get_float(key):
            v = request.data.get(key)
            return float(v) if v is not None else None

        # ═══════════════════════════════════════════════════
        # [C′-3a v2.1] R&D 시나리오 라벨 추출
        # fastapi_generator 가 토글된 device 마다 동봉.
        # 없으면 모두 None (레거시 호환).
        # ═══════════════════════════════════════════════════
        ep_raw = request.data.get('expected_phase')
        labels = {
            'scenario_id':     request.data.get('scenario_id'),
            'expected_phase':  int(ep_raw) if ep_raw is not None else None,
            'expected_status': request.data.get('expected_status'),
        }

        if sensor_type == 'gas':
            sd, s, payload_values, is_ai, ai_detail = self._save_gas(device, _get_float, labels)
        elif sensor_type == 'power':
            sd, s, payload_values, is_ai, ai_detail = self._save_power(device, _get_float, labels)
        else:
            return Response(
                {'error': f'미지원 sensor_type: {sensor_type}'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        device.status = s
        device.save(update_fields=['status', 'last_value'])

        publish_sensor_update({
            "device_id":   device.device_id,
            "sensor_type": sensor_type,
            "status":      s,
            "values":      payload_values,
            "timestamp":   sd.timestamp.isoformat(),
        })

        # ─── 알람 평가 (모든 POST 마다 호출, 즉시 알람 보장) ───
        # evaluate_sensor 내부에서 official_state vs observed_status 비교로 알람 결정:
        # - 진짜 임계 초과 (classify_gas → caution/danger) → transition 알람 즉시 + Slack
        # - 지속 caution/danger → RE_ALARM_INTERVAL_SEC(60s) 마다 ongoing 알람
        # - normal 복귀 → recovery 알람 1회
        # - status 변화 없음 → 0건 반환 (cheap)
        # is_ai=True 시 ai_detail (ARIMA 결과) 도 메시지에 포함.
        alarms = evaluate_sensor(
            device_id=device.device_id,
            sensor_type=sensor_type,
            observed_status=s,
            detail=(ai_detail if is_ai else ''),
            is_ai=is_ai,
            ai_detail=ai_detail,
        )
        for alarm in alarms:
            publish_alarm(alarm)

        return Response(
            {'id': sd.id, 'status': s, 'is_ai': is_ai},
            status=http_status.HTTP_201_CREATED,
        )

    def _save_gas(self, device, _get_float, labels):
        gas = {
            'co':  _get_float('co'),  'h2s': _get_float('h2s'),
            'co2': _get_float('co2'), 'o2':  _get_float('o2'),
            'no2': _get_float('no2'), 'so2': _get_float('so2'),
            'o3':  _get_float('o3'),  'nh3': _get_float('nh3'),
            'voc': _get_float('voc'),
        }
        s = classify_gas(gas)
        is_ai = False
        ai_detail = ''

        # ─── ARIMA 이상 탐지 (보조) ───
        # [D 분리] sensor.status 갱신 안 함 (classify_gas 임계 기반만 사용).
        # ARIMA 의 9가스 OR + 3σ + online learning 조합은 false positive 폭증 구조.
        # ARIMA 의 anomaly 탐지 결과는 ai_detail 로 기록 (AI 알람 채널 별도 유지).
        if s == 'normal':
            anomaly_kinds = []
            for key, val in gas.items():
                if val is not None:
                    if detect_anomaly(device.device_id, f'gas_{key}', val):
                        anomaly_kinds.append(GAS_LABELS.get(key, key.upper()))
            if anomaly_kinds:
                # s = 'caution'   ← 제거: sensor.status 안 잠금
                is_ai = True
                ai_detail = 'ARIMA: ' + ', '.join(anomaly_kinds)

        # ─── IsolationForest 추세 예측 ───
        for key, val in gas.items():
            if val is None:
                continue
            threshold = GAS_THRESHOLDS_CAUTION.get(key)
            if not threshold:
                continue
            # 미결 예측 검증
            verify_predictions(device.device_id, key, val, threshold)
            # 새 예측 (현재 정상 상태일 때만)
            if s == 'normal':
                pred_info = predict_trend(device.device_id, key, val, threshold)
                if pred_info:
                    self._create_ai_prediction(
                        device=device,
                        sensor_key=key,
                        sensor_type='gas',
                        value=val,
                        threshold=threshold,
                        pred_info=pred_info,
                        label=GAS_LABELS.get(key, key.upper()),
                    )

        # SensorData 저장 — C′-3a 라벨 컬럼 포함
        sd = SensorData.objects.create(
            device=device,
            co=gas['co'],   h2s=gas['h2s'], co2=gas['co2'], o2=gas['o2'],
            no2=gas['no2'], so2=gas['so2'], o3=gas['o3'],
            nh3=gas['nh3'], voc=gas['voc'],
            status=s,
            scenario_id=labels['scenario_id'],
            expected_phase=labels['expected_phase'],
            expected_status=labels['expected_status'],
        )
        if gas['co'] is not None:
            device.last_value = gas['co']
        return sd, s, gas, is_ai, ai_detail

    def _save_power(self, device, _get_float, labels):
        power = {
            'current': _get_float('current'),
            'voltage': _get_float('voltage'),
            'watt':    _get_float('watt'),
        }
        s = classify_power(power, device.device_id)
        is_ai = False
        ai_detail = ''

        # ─── ARIMA 이상 탐지 (보조) ───
        if s == 'normal' and power['watt'] is not None:
            if detect_anomaly(device.device_id, 'power_watt', power['watt']):
                s = 'caution'
                is_ai = True
                ai_detail = '전력'

        # ─── IsolationForest 추세 예측 ───
        if power['watt'] is not None:
            # 전력 caution 임계치: 고정값 3000W (classify_power fallback 기준)
            watt_threshold = 3000.0
            verify_predictions(device.device_id, 'watt', power['watt'], watt_threshold)
            if s == 'normal':
                pred_info = predict_trend(
                    device.device_id, 'watt', power['watt'], watt_threshold
                )
                if pred_info:
                    self._create_ai_prediction(
                        device=device,
                        sensor_key='watt',
                        sensor_type='power',
                        value=power['watt'],
                        threshold=watt_threshold,
                        pred_info=pred_info,
                        label='전력',
                    )

        # SensorData 저장 — C′-3a 라벨 컬럼 포함
        sd = SensorData.objects.create(
            device=device,
            current=power['current'],
            voltage=power['voltage'],
            watt=power['watt'],
            status=s,
            scenario_id=labels['scenario_id'],
            expected_phase=labels['expected_phase'],
            expected_status=labels['expected_status'],
        )
        if power['watt'] is not None:
            device.last_value = power['watt']
        return sd, s, power, is_ai, ai_detail

    def _create_ai_prediction(self, device, sensor_key, sensor_type,
                               value, threshold, pred_info, label):
        """AIPrediction 기록 + 알람 생성. sensor + gas 별 60초 throttle 적용."""
        # [Throttle] sensor + gas 별 직전 알람으로부터 60초 이내면 skip
        cache_key = (device.device_id, sensor_key)
        now_t = time.time()
        with _ai_pred_throttle_lock:
            last_t = _ai_pred_throttle.get(cache_key, 0.0)
            if now_t - last_t < _AI_PRED_THROTTLE_SEC:
                return   # 60초 안 지남 — 알람/AIPrediction 생성 skip
            _ai_pred_throttle[cache_key] = now_t

        expires_at = timezone.now() + timedelta(seconds=pred_info['predicted_ticks'] * 5)

        message = (
            f"AI예측 - {device.device_id} {label} "
            f"약 {pred_info['predicted_ticks']}틱 후 임계치 초과 예상 "
            f"(현재 {value:.2f} → 예상 {pred_info['predicted_value']:.2f})"
        )

        alarm = Alarm.objects.create(
            alarm_type='ai_prediction',
            alarm_level='caution',
            device_id=device.device_id,
            sensor_type=sensor_type,
            message=message,
            is_ai=True,
        )

        AIPrediction.objects.create(
            device_id=device.device_id,
            sensor_key=sensor_key,
            sensor_type=sensor_type,
            value_at_predict=value,
            threshold=threshold,
            slope=pred_info['slope'],
            if_score=pred_info['if_score'],
            predicted_ticks=pred_info['predicted_ticks'],
            predicted_value=pred_info['predicted_value'],
            expires_at=expires_at,
            alarm=alarm,
        )

        publish_alarm({
            'alarm_id':    alarm.id,
            'alarm_type':  'ai_prediction',
            'alarm_level': 'caution',
            'device_id':   device.device_id,
            'sensor_type': sensor_type,
            'message':     message,
            'is_ai':       True,
        })

        logger.info("AI예측 생성 [%s/%s] %d틱 후 %.3f 초과 예상",
                    device.device_id, sensor_key,
                    pred_info['predicted_ticks'], threshold)
