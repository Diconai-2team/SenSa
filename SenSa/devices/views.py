"""
devices/views.py — 센서 장비 CRUD + 센서 데이터 수신/저장

AI 파이프라인 구조 (방식 B):
  데이터 수신 시 두 개의 백그라운드 스레드를 동시에 시작:
    스레드 A: _run_evaluate_sensor() — 임계치 기반 상태 전이 알람 (evaluate_sensor)
    스레드 B: _run_ai_pipeline()    — ml_engine AI 파이프라인 (5종 탐지기 + 상관관계 + 확산)
"""
import logging
import random as _random
import threading as _threading
import time as _time
from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets, status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Device, SensorData
from .serializers import DeviceSerializer
from realtime.publishers import publish_sensor_update, publish_alarm, publish_ai_prediction

from alerts.services import classify_gas, classify_power, evaluate_sensor
from alerts.services.classifiers import GAS_THRESHOLDS, O2_DANGER_LOW, O2_CAUTION_LOW, O2_CAUTION_HIGH, O2_DANGER_HIGH
from alerts.models import Alarm, AIPrediction
from ml_engine import pipeline as ai_pipeline

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 가스 / 전력 메트릭 목록
# ═══════════════════════════════════════════════════════════
_GAS_METRICS   = ['co', 'h2s', 'co2', 'o2', 'no2', 'so2', 'o3', 'nh3', 'voc']
_POWER_METRICS = ['current', 'voltage', 'watt']

GAS_LABELS = {
    'co':  'CO',  'h2s': 'H2S', 'co2': 'CO2', 'o2':  'O2',
    'no2': 'NO2', 'so2': 'SO2', 'o3':  'O3',  'nh3': 'NH3', 'voc': 'VOC',
}

# ═══════════════════════════════════════════════════════════
# AI 파이프라인 — 동시 실행 제한 (GIL thundering herd 방지)
# ═══════════════════════════════════════════════════════════
_AI_SEMAPHORE = _threading.Semaphore(2)

# AI 상태 → Alarm 타입 + 기본 레벨 매핑
_AI_ALARM_MAP = {
    "ML_ANOMALY":         ("ai_ml_anomaly",         "danger"),
    "ANOMALY_WARNING":    ("ai_anomaly_warning",     "caution"),
    "TREND_SHIFT":        ("ai_trend_shift",         "caution"),
    "PREDICTIVE_ALERT":   ("ai_predictive_alert",    "caution"),
    "PREDICTIVE_WARNING": ("ai_predictive_warning",  "caution"),
    "DRIFT_ALERT":        ("ai_drift_alert",         "caution"),
}

# ═══════════════════════════════════════════════════════════
# 에스컬레이션 — 같은 알람 반복 시 레벨 상향
# ═══════════════════════════════════════════════════════════
ESCALATION_THRESHOLD  = 3
ESCALATION_WINDOW_SEC = 300   # [운영 전환 시] → 600

_LEVEL_ORDER = ["info", "caution", "danger", "critical"]
_esc_lock  = _threading.Lock()
_esc_state: dict = {}  # "device:metric:alarm_type" → {"count": int, "last_seen": float}

# 에스컬레이션 제외 타입:
#   DRIFT_ALERT — CUSUM은 만성적 추세로 caution→danger 상향이 의미 없음.
#                 게다가 91.8%의 drift 알람이 escalation으로 300s 쿨다운을 우회하고 있었음.
#   PREDICTIVE_* — 미래 예측이므로 아직 현실화되지 않은 위험을 danger로 올리면 혼란.
_NO_ESCALATION_TYPES = {'ai_drift_alert', 'ai_predictive_warning', 'ai_predictive_alert'}

# ═══════════════════════════════════════════════════════════
# 알람 쿨다운 (중복 억제)
# ═══════════════════════════════════════════════════════════
_GAS_COOLDOWN_SEC  = 30    # 가스 AI 알람 쿨다운 [운영 전환 시] → 120
_BASE_COOLDOWN_SEC = 10    # 전력·에스컬레이션 쿨다운 [운영 전환 시] → 60

# 드리프트 device 레벨 쿨다운:
#   CUSUM이 9개 메트릭을 각각 판정하므로 같은 틱에 9건 동시 발화.
#   device 단위로 쿨다운을 추가해 틱당 1건으로 제한.
_device_drift_ts: dict = {}   # device_id → last drift alarm posix timestamp
_ddrift_lock = _threading.Lock()

# ═══════════════════════════════════════════════════════════
# 위험 임박 우선 통과 기준
# ═══════════════════════════════════════════════════════════
_BYPASS_DETECTOR_MIN = 3    # 탐지기 N개 이상 동시 발화
_BYPASS_VALUE_RATIO  = 2.0  # 마지막 알람 이후 농도 N배 급등
_BYPASS_DANGER_RATIO = 0.8  # 위험 임계치의 80% 이상 도달

_last_alarm_values: dict = {}  # "device_id:metric" → {"value": float, "ts": float}
_lav_lock = _threading.Lock()

# ═══════════════════════════════════════════════════════════
# 상관관계 분석 상수
# ═══════════════════════════════════════════════════════════
_COMBUSTIBLE_GAS       = {'co', 'h2s', 'no2', 'so2', 'o3', 'nh3', 'voc'}
_O2_DISPLACEMENT_TH    = 19.5
_MULTI_GAS_ANOMALY_MIN = 3

_CROSS_WINDOW_SEC = 120   # 가스+전력 교차 이상 묶음 시간 [운영 전환 시] → 360
_cross_lock = _threading.Lock()
_recent_gas_anomalies:   dict = {}
_recent_power_anomalies: dict = {}

# 공간 확산 탐지 파라미터
_DIFFUSION_RADIUS    = 500.0
_DIFFUSION_HALF      = 5
_DIFFUSION_RISE_RATE = 0.08   # 8% 이상 상승이면 rising으로 판정

# ═══════════════════════════════════════════════════════════
# Zone 자동 tick (Celery beat 대체 — 30초 주기 백그라운드 스레드)
# ═══════════════════════════════════════════════════════════
def _zone_tick_loop():
    """30초 주기 zone 반경 진화 + 만료 + 승격 (tick() 는 idempotent).

    Celery beat 와 동시에 실행돼도 무해 — tick() 자체가 중복-안전.
    """
    import logging as _log_mod
    from django.db import close_old_connections as _close_old_connections
    _zt_logger = _log_mod.getLogger('geofence.zone_tick')
    while True:
        _time.sleep(30)
        try:
            # [수정] 30초 휴면 후 연결이 stale 해질 수 있으므로 매 틱마다 정리.
            # CONN_MAX_AGE > 0 설정(PostgreSQL 운영 환경) 에서도 안전하게 동작.
            _close_old_connections()
            from geofence.zone_lifecycle import tick
            result = tick(check_upgrade=True)
            if any(result.values()):
                _zt_logger.info('[zone_tick] %s', result)
        except Exception as _e:
            _zt_logger.warning('[zone_tick] error: %s', _e)

def _start_zone_tick_thread():
    """zone-tick 스레드 중복 없이 시작 (Django reloader 재임포트 대비)."""
    for t in _threading.enumerate():
        if t.name == 'zone-tick':
            return
    _threading.Thread(target=_zone_tick_loop, daemon=True, name='zone-tick').start()

_start_zone_tick_thread()


# ═══════════════════════════════════════════════════════════
# Views
# ═══════════════════════════════════════════════════════════

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

        # C'-3a: R&D 시나리오 라벨 (없으면 None, 레거시 호환)
        ep_raw = request.data.get('expected_phase')
        labels = {
            'scenario_id':     request.data.get('scenario_id'),
            'expected_phase':  int(ep_raw) if ep_raw is not None else None,
            'expected_status': request.data.get('expected_status'),
        }

        if sensor_type == 'gas':
            sd, s, payload_values = self._save_gas(device, _get_float, labels)
        elif sensor_type == 'power':
            sd, s, payload_values = self._save_power(device, _get_float, labels)
        else:
            return Response(
                {'error': f'미지원 sensor_type: {sensor_type}'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # WebSocket publish + device 상태 갱신 + 알람 + AI 파이프라인 모두 백그라운드.
        # - publish_sensor_update: async_to_sync 블로킹 → 백그라운드 필수
        # - device.save(): SensorData.create 직후 바로 필요 없음 → 백그라운드로 DB 경합 완화
        ws_payload = {
            "device_id":   device.device_id,
            "sensor_type": sensor_type,
            "status":      s,
            "values":      payload_values,
            "timestamp":   sd.timestamp.isoformat(),
        }
        device_pk_for_bg  = device.pk
        detail = _gas_detail(payload_values) if sensor_type == 'gas' else ''

        def _publish_and_update_device():
            from django.db import close_old_connections
            close_old_connections()
            try:
                from devices.models import Device as _Device
                _Device.objects.filter(pk=device_pk_for_bg).update(
                    status=s,
                    last_value=payload_values.get('co') or payload_values.get('watt'),
                )
            except Exception:
                pass
            publish_sensor_update(ws_payload)

        _threading.Thread(target=_publish_and_update_device, daemon=True).start()

        # ─── 스레드 A: 임계치 알람 (evaluate_sensor) ───────────
        _threading.Thread(
            target=_run_evaluate_sensor,
            args=(device.device_id, sensor_type, s, detail),
            daemon=True,
        ).start()

        # ─── 스레드 B: AI 파이프라인 (ml_engine) ───────────────
        if sensor_type == 'gas' and device.sensor_type == 'gas':
            _threading.Thread(
                target=_run_ai_pipeline,
                args=(device.device_id, payload_values),
                daemon=True,
            ).start()
        elif sensor_type == 'power' and device.sensor_type == 'power':
            _threading.Thread(
                target=_run_power_ai_pipeline,
                args=(device.device_id, payload_values),
                daemon=True,
            ).start()

        return Response(
            {'id': sd.id, 'status': s},
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
        return sd, s, gas

    def _save_power(self, device, _get_float, labels):
        power = {
            'current': _get_float('current'),
            'voltage': _get_float('voltage'),
            'watt':    _get_float('watt'),
        }
        s = classify_power(power, device.device_id)
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
        return sd, s, power


# ═══════════════════════════════════════════════════════════
# 스레드 A: 임계치 알람 평가
# ═══════════════════════════════════════════════════════════

def _gas_detail(gas: dict) -> str:
    parts = []
    for key in _GAS_METRICS:
        v = gas.get(key)
        if v is not None:
            parts.append(f"{GAS_LABELS.get(key, key.upper())}:{v:.1f}")
    return ', '.join(parts)


def _run_evaluate_sensor(device_id: str, sensor_type: str,
                          observed_status: str, detail: str) -> None:
    try:
        from django.db import close_old_connections
        close_old_connections()
        alarms = evaluate_sensor(
            device_id=device_id,
            sensor_type=sensor_type,
            observed_status=observed_status,
            detail=detail,
        )
        for alarm in alarms:
            publish_alarm(alarm)
    except Exception as exc:
        logger.warning("[evaluate_sensor] %s: %s", device_id, exc)
    finally:
        from django.db import close_old_connections
        close_old_connections()


# ═══════════════════════════════════════════════════════════
# 스레드 B: AI 파이프라인 — 가스
# ═══════════════════════════════════════════════════════════

def _run_ai_pipeline(device_id: str, gas_values: dict) -> None:
    acquired = _AI_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        return  # 동시 2개 초과 → 이번 틱 스킵
    try:
        _run_ai_pipeline_inner(device_id, gas_values)
    finally:
        _AI_SEMAPHORE.release()


def _run_ai_pipeline_inner(device_id: str, gas_values: dict) -> None:
    # [수정] 예외 발생 시에도 DB 연결이 반드시 반환되도록 try/except/finally 추가.
    # 기존 코드는 함수 끝에 close_old_connections()만 있어 예외 시 연결 누수 발생.
    # _run_evaluate_sensor 와 동일한 패턴으로 통일.
    from django.db import close_old_connections
    try:
        close_old_connections()

        # 스테일 에스컬레이션/알람값 정리 (1% 확률 — 평균 100틱마다 1회)
        if _random.random() < 0.01:
            _cleanup_stale_esc()

        anomaly_metrics = []

        for metric in _GAS_METRICS:
            value = gas_values.get(metric)
            if value is None:
                continue

            # 새 측정값이 들어올 때마다 ARIMA 예측 검증 (pending → success/failure)
            _verify_ai_predictions(device_id, metric, float(value))

            result = ai_pipeline.analyze(device_id, metric, value)

            current = result["current_status"]
            if current != "NORMAL":
                _maybe_create_alarm(device_id, metric, current, result, is_predictive=False)
                anomaly_metrics.append(metric)

            predictive = result["predictive_status"]
            if predictive != "NORMAL":
                _maybe_create_alarm(device_id, metric, predictive, result, is_predictive=True)

            # ARIMA 예측값을 WebSocket 차트용으로 발행
            arima = result["details"].get("arima", {})
            if arima.get("model_ready") and arima.get("predicted_values"):
                publish_ai_prediction({
                    "device_id":       device_id,
                    "metric":          metric,
                    "predicted_values": arima["predicted_values"],
                    "steps":           arima["steps"],
                })

        if anomaly_metrics:
            _record_gas_anomaly(device_id, anomaly_metrics)

        # 가스-가스 상관관계 (2종 이상 동시 이상)
        if len(anomaly_metrics) >= 2:
            _check_gas_correlation(device_id, anomaly_metrics, gas_values)

        # 공간 확산 탐지 (별도 스레드)
        if anomaly_metrics:
            _threading.Thread(
                target=_check_spatial_diffusion,
                args=(device_id, list(anomaly_metrics)),
                daemon=True,
            ).start()

    except Exception as exc:
        logger.warning("[ai_pipeline/gas] %s: %s", device_id, exc)
    finally:
        close_old_connections()


# ═══════════════════════════════════════════════════════════
# 스레드 B: AI 파이프라인 — 전력
# ═══════════════════════════════════════════════════════════

def _run_power_ai_pipeline(device_id: str, power_values: dict) -> None:
    acquired = _AI_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        return
    try:
        _run_power_ai_pipeline_inner(device_id, power_values)
    finally:
        _AI_SEMAPHORE.release()


def _run_power_ai_pipeline_inner(device_id: str, power_values: dict) -> None:
    # [수정] 예외 발생 시에도 DB 연결이 반드시 반환되도록 try/except/finally 추가.
    # 가스 파이프라인(_run_ai_pipeline_inner) 과 동일한 패턴으로 통일.
    from django.db import close_old_connections
    try:
        close_old_connections()

        # 스테일 에스컬레이션/알람값 정리 (1% 확률 — 평균 100틱마다 1회)
        if _random.random() < 0.01:
            _cleanup_stale_esc()

        power_anomalies = []

        for metric in _POWER_METRICS:
            value = power_values.get(metric)
            if value is None:
                continue

            result = ai_pipeline.analyze(device_id, metric, value, sensor_type='power')

            current = result["current_status"]
            if current != "NORMAL":
                _maybe_create_alarm(device_id, metric, current, result, is_predictive=False)
                power_anomalies.append((metric, current))

            predictive = result["predictive_status"]
            if predictive != "NORMAL":
                _maybe_create_alarm(device_id, metric, predictive, result, is_predictive=True)

            # ARIMA 예측값 WebSocket 발행 (차트 점선용)
            arima = result["details"].get("arima", {})
            if arima.get("model_ready") and arima.get("predicted_values"):
                publish_ai_prediction({
                    "device_id":        device_id,
                    "metric":           metric,
                    "predicted_values": arima["predicted_values"],
                    "steps":            arima["steps"],
                })

        if power_anomalies:
            _record_power_anomaly(device_id, [m for m, _ in power_anomalies])
            recent_gas = _get_recent_gas_events()
            if recent_gas:
                _check_power_gas_correlation(device_id, power_anomalies, recent_gas)

    except Exception as exc:
        logger.warning("[ai_pipeline/power] %s: %s", device_id, exc)
    finally:
        close_old_connections()


# ═══════════════════════════════════════════════════════════
# AIPrediction 검증 — 실측값으로 예측 성공/실패 판정
# ═══════════════════════════════════════════════════════════

def _verify_ai_predictions(device_id: str, metric: str, actual_value: float) -> None:
    """
    pending 상태의 AIPrediction을 실측값으로 검증.

    - actual_value >= threshold → 예측 맞음 (success)
    - expires_at 초과 → 임계치 미달, 예측 틀림 (failure)

    DB 호출을 최소화하기 위해 pending 건이 없으면 즉시 리턴.
    """
    now = timezone.now()
    pending = list(
        AIPrediction.objects.filter(
            device_id=device_id,
            sensor_key=metric,
            result='pending',
        ).only('id', 'threshold', 'expires_at')
    )
    if not pending:
        return

    success_ids = []
    failure_ids = []
    for pred in pending:
        if actual_value >= pred.threshold:
            success_ids.append(pred.id)
        elif now >= pred.expires_at:
            failure_ids.append(pred.id)

    if success_ids:
        AIPrediction.objects.filter(pk__in=success_ids).update(result='success')
    if failure_ids:
        AIPrediction.objects.filter(pk__in=failure_ids).update(result='failure')

    # ── AIPrediction 결과 → ARIMA 피드백 루프 ───────────────────────────────
    # 성공/실패를 arima_forecaster 에 알려 연속 실패 시 조기 재학습을 트리거.
    # 실패가 EARLY_RETRAIN_THRESHOLD(=3)회 연속이면 캐시 무효화 → 다음 틱 재학습.
    # lazy import — 순환 import 방지 및 실패 시 알람 생성 흐름 보호.
    try:
        from ml_engine.arima_forecaster import (
            record_prediction_success,
            record_prediction_failure,
        )
        if success_ids:
            record_prediction_success(device_id, metric)
        if failure_ids:
            record_prediction_failure(device_id, metric)
    except Exception:
        pass   # 피드백 실패가 알람 파이프라인을 중단하면 안 됨


# ═══════════════════════════════════════════════════════════
# 알람 생성 — 중복 억제 + 에스컬레이션 + AIPrediction 연동
# ═══════════════════════════════════════════════════════════

def _maybe_create_alarm(
    device_id: str,
    metric: str,
    ai_status: str,
    result: dict,
    is_predictive: bool,
) -> None:
    alarm_type, base_level = _AI_ALARM_MAP.get(ai_status, (None, None))
    if alarm_type is None:
        return

    now = timezone.now()

    base_cutoff = now - timedelta(seconds=_BASE_COOLDOWN_SEC)
    recent_60s = Alarm.objects.filter(
        device_id=device_id,
        sensor_type=metric,
        alarm_type=alarm_type,
        created_at__gte=base_cutoff,
    ).exists()

    final_level = base_level
    escalated = False
    # 에스컬레이션 제외 타입은 레벨 상향 없이 쿨다운만 적용
    if not recent_60s and alarm_type not in _NO_ESCALATION_TYPES:
        final_level, esc_count = _escalate_level(device_id, metric, alarm_type, base_level)
        escalated = final_level != base_level

    current_value = result.get("current_value") or 0.0
    bypass = (
        not is_predictive
        and not escalated
        and metric in _GAS_METRICS
        and _is_danger_imminent(device_id, metric, current_value, result.get("detector_count", 0))
    )

    # ── 임계치 알람 연계: 같은 기간 내 threshold 알람이 이미 있으면 AI 현재 상태 알람 억제 ──
    # 예측 알람(is_predictive)·에스컬레이션(escalated) 은 제외 — 사전 경보 / 반복 악화는 알려야 함.
    # 이유: sensor_caution/danger 가 이미 발행됐다면 AI 알람은 같은 사건의 중복 표시.
    #       threshold 알람의 sensor_type='gas'/'power' (메트릭별 아닌 장비 단위) 이므로
    #       device_id + sensor_category + 알람 유형으로 조회.
    if not is_predictive and not escalated:
        sensor_category = 'gas' if metric in _GAS_METRICS else 'power'
        th_cooldown = _GAS_COOLDOWN_SEC if metric in _GAS_METRICS else _BASE_COOLDOWN_SEC
        th_cutoff   = now - timedelta(seconds=th_cooldown)
        if Alarm.objects.filter(
            device_id=device_id,
            sensor_type=sensor_category,
            alarm_type__in=['sensor_caution', 'sensor_danger'],
            created_at__gte=th_cutoff,
        ).exists():
            return

    if escalated:
        pass
    elif bypass:
        if recent_60s:
            return
    else:
        if metric in _GAS_METRICS:
            if recent_60s:
                return
            long_cutoff = now - timedelta(seconds=_GAS_COOLDOWN_SEC)
            if Alarm.objects.filter(
                device_id=device_id,
                sensor_type=metric,
                alarm_type=alarm_type,
                created_at__gte=long_cutoff,
            ).exists():
                return
        else:
            # 전력 메트릭: drift는 300s, 나머지는 60s 쿨다운
            if alarm_type == 'ai_drift_alert':
                long_cutoff = now - timedelta(seconds=_GAS_COOLDOWN_SEC)
                if Alarm.objects.filter(
                    device_id=device_id,
                    sensor_type=metric,
                    alarm_type=alarm_type,
                    created_at__gte=long_cutoff,
                ).exists():
                    return
            elif recent_60s:
                return

    # drift: device 레벨 쿨다운 — 다른 메트릭이 같은 틱에 이미 drift 알람을 냈으면 차단
    if alarm_type == 'ai_drift_alert':
        now_ts = _time.time()
        with _ddrift_lock:
            last_ts = _device_drift_ts.get(device_id, 0.0)
            if now_ts - last_ts < _GAS_COOLDOWN_SEC:
                return

    # 메시지 생성
    if is_predictive:
        pred = result["details"]["arima"]
        msg = (
            f"[AI예측] {device_id} / {metric.upper()} "
            f"— 10틱 후 {pred.get('predicted_max', '?')} 도달 예상 ({ai_status})"
        )
    elif ai_status == "DRIFT_ALERT":
        cusum = result["details"]["cusum"]
        direction = cusum.get("direction", "up")
        direction_label = "서서히 상승 중" if direction == "up" else "서서히 하강 중"
        baseline = cusum.get("mu")
        concern = "누출 의심" if direction == "up" else "산소 결핍 의심"
        msg = (
            f"[AI드리프트] {device_id} / {metric.upper()} "
            f"— {direction_label} (기준값 {baseline}, {concern})"
        )
    else:
        msg = (
            f"[AI탐지] {device_id} / {metric.upper()} "
            f"— {ai_status} (윈도우 {result['window_size']}개)"
        )

    if escalated:
        msg += f" ⚠ 지속 {esc_count}회 — 레벨 상향"
    if bypass:
        msg += " ⚡ 위험 임박 — 쿨다운 우선 통과"

    alarm = Alarm.objects.create(
        alarm_type=alarm_type,
        alarm_level=final_level,
        device_id=device_id,
        sensor_type=metric,
        message=msg,
        is_ai=True,
    )

    # drift: device 레벨 쿨다운 타임스탬프 갱신 (알람 생성 성공 후)
    if alarm_type == 'ai_drift_alert':
        with _ddrift_lock:
            _device_drift_ts[device_id] = _time.time()

    # ARIMA 예측 알람인 경우 AIPrediction 기록 (자동 검증용)
    if is_predictive:
        arima = result["details"].get("arima", {})
        predicted_max = arima.get("predicted_max")
        if predicted_max is not None:
            # [수정] O2 는 GAS_THRESHOLDS 에 없어 None 이 되던 버그 수정
            # O2_CAUTION_LOW 를 단일 출처(classifiers.py)에서 직접 사용
            if metric == 'o2':
                caution_th = O2_CAUTION_LOW
            else:
                caution_th = GAS_THRESHOLDS.get(metric, {}).get('caution')

            if caution_th:
                steps = arima.get("steps", 10)
                # [수정] slope·if_score 실제 값 채우기 (구 trend_predictor 0.0 하드코딩 제거)
                if_detail = result["details"].get("isolation_forest", {})
                AIPrediction.objects.create(
                    device_id=device_id,
                    sensor_key=metric,
                    sensor_type='gas' if metric in _GAS_METRICS else 'power',
                    value_at_predict=float(current_value),
                    threshold=float(caution_th),
                    slope=if_detail.get("slope", 0.0),       # IF slope feature
                    if_score=if_detail.get("score", 0.0),    # IF anomaly score
                    predicted_ticks=steps,
                    predicted_value=float(predicted_max),
                    # 예측 지평선의 3배 시간을 검증 창으로 줌 (시뮬 1틱=1s 기준 30s)
                    expires_at=now + timedelta(seconds=steps * 3),
                    alarm=alarm,
                )

    if not is_predictive and metric in _GAS_METRICS and current_value > 0:
        with _lav_lock:
            _last_alarm_values[f"{device_id}:{metric}"] = {
                "value": current_value,
                "ts":    _time.time(),
            }

    publish_alarm({
        "alarm_id":    alarm.id,
        "alarm_type":  alarm_type,
        "alarm_level": final_level,
        "device_id":   device_id,
        "metric":      metric,
        "ai_status":   ai_status,
        "message":     msg,
    })


# ═══════════════════════════════════════════════════════════
# 에스컬레이션
# ═══════════════════════════════════════════════════════════

def _escalate_level(device_id: str, metric: str, alarm_type: str, base_level: str) -> tuple:
    key = f"{device_id}:{metric}:{alarm_type}"
    now = _time.time()
    with _esc_lock:
        entry = _esc_state.get(key)
        if entry is None or now - entry["last_seen"] > ESCALATION_WINDOW_SEC:
            new_count = 1
        else:
            new_count = entry["count"] + 1
        _esc_state[key] = {"count": new_count, "last_seen": now}

    if new_count < ESCALATION_THRESHOLD:
        return base_level, new_count

    try:
        idx = _LEVEL_ORDER.index(base_level)
        return _LEVEL_ORDER[min(idx + 1, len(_LEVEL_ORDER) - 1)], new_count
    except ValueError:
        return base_level, new_count


# ═══════════════════════════════════════════════════════════
# 위험 임박 판정
# ═══════════════════════════════════════════════════════════

def _is_danger_imminent(
    device_id: str,
    metric: str,
    current_value: float,
    detector_count: int,
) -> bool:
    if current_value <= 0:
        return False

    if detector_count >= _BYPASS_DETECTOR_MIN:
        return True

    if metric == 'o2':
        # 저농도 bypass: O2 결핍 위험 (값이 낮을수록 위험)
        # danger=16%, caution=18%, ratio=0.8 → 16 + 2×0.2 = 16.4% 이하
        low_th = O2_DANGER_LOW + (O2_CAUTION_LOW - O2_DANGER_LOW) * (1 - _BYPASS_DANGER_RATIO)
        if current_value <= low_th:
            return True
        # 고농도 bypass: O2 과잉 공급 위험 (값이 높을수록 위험)
        # caution=21.5%, danger=23.5%, ratio=0.8 → 21.5 + 2×0.8 = 23.1% 이상
        high_th = O2_CAUTION_HIGH + (O2_DANGER_HIGH - O2_CAUTION_HIGH) * _BYPASS_DANGER_RATIO
        if current_value >= high_th:
            return True
    else:
        t = GAS_THRESHOLDS.get(metric)
        if t and current_value >= t['danger'] * _BYPASS_DANGER_RATIO:
            return True

    if metric != 'o2':
        with _lav_lock:
            last = _last_alarm_values.get(f"{device_id}:{metric}")
        if last and last['value'] > 0 and current_value / last['value'] >= _BYPASS_VALUE_RATIO:
            return True

    return False


# ═══════════════════════════════════════════════════════════
# 교차 상관관계 — 가스-가스
# ═══════════════════════════════════════════════════════════

def _evict_stale_cross_events() -> None:
    now = _time.time()
    stale = [k for k, v in _recent_gas_anomalies.items() if now - v["ts"] > _CROSS_WINDOW_SEC]
    for k in stale:
        del _recent_gas_anomalies[k]
    stale = [k for k, v in _recent_power_anomalies.items() if now - v["ts"] > _CROSS_WINDOW_SEC]
    for k in stale:
        del _recent_power_anomalies[k]


# 에스컬레이션 / 마지막 알람값 스테일 항목 정리
# 기술부채 A: _esc_state, _last_alarm_values 는 삭제 로직이 없어 장기 운영 시 누적.
# _run_ai_pipeline_inner / _run_power_ai_pipeline_inner 진입 시 1% 확률로 호출
# → 평균 100 틱(~100초)마다 1회 정리. O(n) 이지만 n은 장비수×metric 수로 제한적.
# TODO(tech-debt): Gunicorn multi-worker 전환 시 Redis로 이전 필요
_ESC_MAX_AGE_SEC = 3600.0    # 1시간 미접근 시 제거
_LAV_MAX_AGE_SEC = 1800.0    # 30분 미접근 시 제거 (gas cooldown 300s의 6배)

def _cleanup_stale_esc() -> None:
    now = _time.time()
    with _esc_lock:
        stale_esc = [k for k, v in _esc_state.items()
                     if now - v["last_seen"] > _ESC_MAX_AGE_SEC]
        for k in stale_esc:
            del _esc_state[k]
    with _lav_lock:
        stale_lav = [k for k, v in _last_alarm_values.items()
                     if now - v["ts"] > _LAV_MAX_AGE_SEC]
        for k in stale_lav:
            del _last_alarm_values[k]


def _record_gas_anomaly(device_id: str, metrics: list) -> None:
    with _cross_lock:
        _recent_gas_anomalies[device_id] = {"metrics": list(metrics), "ts": _time.time()}
        _evict_stale_cross_events()


def _record_power_anomaly(device_id: str, metrics: list) -> None:
    with _cross_lock:
        _recent_power_anomalies[device_id] = {"metrics": list(metrics), "ts": _time.time()}
        _evict_stale_cross_events()


def _get_recent_gas_events() -> list:
    now = _time.time()
    with _cross_lock:
        return [
            {"device_id": dev, "metrics": e["metrics"]}
            for dev, e in _recent_gas_anomalies.items()
            if now - e["ts"] <= _CROSS_WINDOW_SEC
        ]


def _check_gas_correlation(
    device_id: str,
    anomaly_metrics: list,
    gas_values: dict,
) -> None:
    """
    규칙 1: O2 치환 감지 — O2 < 19.5% AND 가연/유해 가스 이상 동시 감지
    규칙 2: 복합 가스 이상 — 3종 이상 동시 AI 이상
    """
    o2_val = gas_values.get('o2')

    if o2_val is not None and o2_val < _O2_DISPLACEMENT_TH:
        combustible = [m for m in anomaly_metrics if m in _COMBUSTIBLE_GAS]
        if combustible:
            _create_correlation_alarm(
                device_id=device_id,
                alarm_level='danger',
                message=(
                    f"[AI상관] {device_id} — O2 {o2_val:.1f}% 하락 + "
                    f"{'/'.join(m.upper() for m in combustible)} 이상 동시 감지 "
                    f"(가스 치환 의심, 즉시 대피)"
                ),
                tag='o2_displacement',
            )

    if len(anomaly_metrics) >= _MULTI_GAS_ANOMALY_MIN:
        _create_correlation_alarm(
            device_id=device_id,
            alarm_level='danger',
            message=(
                f"[AI상관] {device_id} — {len(anomaly_metrics)}종 가스 동시 이상 "
                f"({', '.join(m.upper() for m in anomaly_metrics)}) 복합 오염 의심"
            ),
            tag='multi_gas',
        )


# ═══════════════════════════════════════════════════════════
# 공간 확산 탐지
# ═══════════════════════════════════════════════════════════

def _is_rising(values: list) -> bool:
    n = _DIFFUSION_HALF
    if len(values) < n * 2:
        return False
    from statistics import mean as _mean
    prev_mean = _mean(values[-n * 2:-n])
    curr_mean = _mean(values[-n:])
    if prev_mean < 1e-9:
        return curr_mean > 1e-9
    return (curr_mean - prev_mean) / prev_mean >= _DIFFUSION_RISE_RATE


def _check_spatial_diffusion(device_id: str, anomaly_metrics: list) -> None:
    try:
        from devices.models import Device
        from ml_engine.sliding_window import get_values as _get_win
        import math

        try:
            src = Device.objects.get(device_id=device_id, is_active=True)
        except Device.DoesNotExist:
            return

        candidates = Device.objects.filter(
            sensor_type='gas', is_active=True
        ).exclude(device_id=device_id)

        rising_neighbors = []
        for dev in candidates:
            dist = math.hypot(dev.x - src.x, dev.y - src.y)
            if dist > _DIFFUSION_RADIUS:
                continue
            for metric in anomaly_metrics:
                if metric == 'o2':
                    continue
                vals = _get_win(dev.device_id, metric)
                if _is_rising(vals):
                    rising_neighbors.append((dev.device_id, metric, round(dist, 1)))
                    break

        if len(rising_neighbors) >= 2:
            neighbor_desc = ', '.join(f"{did}({m})" for did, m, _ in rising_neighbors)
            _create_correlation_alarm(
                device_id=device_id,
                alarm_level='danger',
                message=(
                    f"[AI확산] {device_id} — "
                    f"{'/'.join(m.upper() for m in anomaly_metrics)} 이상 탐지 후 "
                    f"인근 센서 {len(rising_neighbors)}개 동시 상승: {neighbor_desc} "
                    f"(가스 확산 의심)"
                ),
                tag='diffusion',
            )

            # 동적 zone 생성 — 이미 활성 zone 없을 때만 (중복 방지)
            _gas_metric = next((m for m in anomaly_metrics if m != 'o2'), None)
            if _gas_metric:
                try:
                    from geofence.models import GeoFence
                    from geofence.zone_lifecycle import create_dynamic_zone
                    already = GeoFence.objects.filter(
                        source_device=src, is_dynamic=True, is_active=True,
                    ).exists()
                    if not already:
                        create_dynamic_zone(
                            src, _gas_metric, trigger_source='diffusion',
                        )
                except Exception as _ze:
                    logger.warning("[diffusion zone] %s: %s", device_id, _ze)
    except Exception as exc:
        logger.warning("[diffusion] %s: %s", device_id, exc)
    finally:
        from django.db import close_old_connections
        close_old_connections()


# ═══════════════════════════════════════════════════════════
# 교차 상관관계 — 전력-가스
# ═══════════════════════════════════════════════════════════

def _check_power_gas_correlation(
    power_device_id: str,
    power_anomalies: list,
    recent_gas_events: list,
) -> None:
    """전류/전력 AI 이상 + 최근 2분 내 가스 이상 → 전기 화재 의심"""
    concern_metrics = [
        m for m, status in power_anomalies
        if m in ('current', 'watt') and status in ('ML_ANOMALY', 'DRIFT_ALERT')
    ]
    if not concern_metrics:
        return

    for gas_event in recent_gas_events:
        _create_correlation_alarm(
            device_id=power_device_id,
            alarm_level='danger',
            message=(
                f"[AI상관] 전력({power_device_id}) "
                f"{'/'.join(m.upper() for m in concern_metrics)} 이상 "
                f"+ 가스({gas_event['device_id']}) "
                f"{'/'.join(m.upper() for m in gas_event['metrics'])} 이상 동시 감지 "
                f"— 전기 화재 의심"
            ),
            tag='power_gas',
        )


def _create_correlation_alarm(
    device_id: str,
    alarm_level: str,
    message: str,
    tag: str,
) -> None:
    """상관관계 알람 생성 (60초 중복 억제).

    [수정] sensor_type 에 태그값('o2_displacement' 등) 대신 'gas'/'power' 올바른 값 저장.
    이전: sensor_type=tag  → sensor_type 필드에 비표준 태그가 섞여 필터 오동작.
    변경: sensor_type='gas'/'power' 고정, 태그는 중복 억제에만 사용 후 폐기.

    60초 내 같은 device_id + alarm_type + sensor_type 조합이 있으면 억제.
    (같은 장치에서 gas 상관관계 alarm이 60초 내 여러 종류 나오면 같은 사건으로 묶임)
    """
    sensor_type = 'power' if tag == 'power_gas' else 'gas'
    cutoff = timezone.now() - timedelta(seconds=60)
    if Alarm.objects.filter(
        device_id=device_id,
        alarm_type='ai_correlation',
        sensor_type=sensor_type,
        created_at__gte=cutoff,
    ).exists():
        return

    alarm = Alarm.objects.create(
        alarm_type='ai_correlation',
        alarm_level=alarm_level,
        device_id=device_id,
        sensor_type=sensor_type,
        message=message,
        is_ai=True,
    )
    publish_alarm({
        "alarm_id":    alarm.id,
        "alarm_type":  'ai_correlation',
        "alarm_level": alarm_level,
        "device_id":   device_id,
        "message":     message,
    })
