"""
devices/views.py — 센서 장비 CRUD + 센서 데이터 수신/저장

[변경 이력]
  Phase D : 4종 가스 저장 + publish_sensor_update
  Gas 병합: 9종 가스 확장 + 통일 임계치
  Power 병합:
    - POST /sensor-data/ 가 gas / power 양쪽 수용
    - power 타입이면 current/voltage/watt 저장 + alerts.services.classify_power 위임
    - 동적 전력 판정(24h 중앙값)이 실제로 돌려면 이 저장 경로가 필수
  Step 1A (가스 패널 페이지네이션화):
    - DeviceViewSet 에 sensor_type 쿼리 필터 추가
      → /dashboard/api/device/?sensor_type=gas 로 가스 센서만 받아갈 수 있음
      → 대시보드 가스/전력 패널이 자기 종류 센서 목록만 페이지네이션 구성용으로 사용

[설계 원칙]
  - status 판정은 이 뷰가 단일 출처 → alerts.services 의 classify_* 재사용
  - 판정 로직을 이 파일에서 복제하지 않고 alerts.services 를 신뢰
  - publish_sensor_update 시그니처 불변
"""
from rest_framework import viewsets, status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Device, SensorData
from .serializers import DeviceSerializer
from realtime.publishers import publish_sensor_update
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

# 판정 로직은 alerts.services 에 단일 정의 — 여기서는 호출만
from alerts.services import (
    classify_gas, classify_power, evaluate_sensor, GAS_THRESHOLDS,
    O2_DANGER_LOW, O2_CAUTION_LOW,
)

# AI 파이프라인 (ml_engine)
from ml_engine import pipeline as ai_pipeline
from alerts.models import Alarm
from realtime.publishers import publish_alarm, publish_ai_prediction


# ═══════════════════════════════════════════════════════════
# Device CRUD
# ═══════════════════════════════════════════════════════════

class DeviceViewSet(viewsets.ModelViewSet):
    """
    센서 장비 CRUD API.

    [필터]
      ?sensor_type=gas|power|temperature|motion
        한 종류의 센서 목록만 받아갈 때 사용.
        대시보드 가스/전력 패널이 페이지네이션 구성용으로 호출.
    """
    queryset = Device.objects.filter(is_active=True)
    serializer_class = DeviceSerializer

    def get_queryset(self):
        """sensor_type 쿼리 파라미터로 필터링 지원 (Step 1A)."""
        qs = super().get_queryset()
        sensor_type = self.request.query_params.get('sensor_type')
        if sensor_type:
            qs = qs.filter(sensor_type=sensor_type)
        return qs


# ═══════════════════════════════════════════════════════════
# 센서 측정값 조회/생성 — gas / power 양쪽 수용
# ═══════════════════════════════════════════════════════════

@method_decorator(csrf_exempt, name='dispatch')
class SensorDataView(APIView):
    """
    센서 데이터 히스토리 API

    GET  ?device_id=sensor_01&limit=20

    POST (gas):
      {"device_id": "sensor_01", "sensor_type": "gas",
       "co": 12.3, "h2s": 2.1, ..., "voc": 0.15}

    POST (power):
      {"device_id": "power_01", "sensor_type": "power",
       "current": 12.3, "voltage": 220.1, "watt": 2712.5}

    응답(POST): {"id": <sd_id>, "status": "normal"|"caution"|"danger"}

    sensor_type 누락 시 기존 호환을 위해 gas 로 간주.
    """

    # ─── 조회 ───
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
            # 가스 9종
            'co': d.co, 'h2s': d.h2s, 'co2': d.co2, 'o2': d.o2,
            'no2': d.no2, 'so2': d.so2, 'o3': d.o3, 'nh3': d.nh3, 'voc': d.voc,
            # 전력 3종 (Power 병합)
            'current': d.current, 'voltage': d.voltage, 'watt': d.watt,
            'status': d.status,
        } for d in reversed(list(data))]
        return Response({'device_id': device_id, 'data': result})

    # ─── 생성 ───
    def post(self, request):
        device_id = request.data.get('device_id')
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=http_status.HTTP_404_NOT_FOUND)

        # sensor_type 추출 — 명시되지 않으면 Device.sensor_type 으로 fallback
        sensor_type = request.data.get('sensor_type') or device.sensor_type

        def _get_float(key):
            v = request.data.get(key)
            return float(v) if v is not None else None

        # ═══════════════════════════════════════════════════
        # 분기: gas / power 별로 파싱 + 판정 + 저장
        # ═══════════════════════════════════════════════════
        if sensor_type == 'gas':
            sd, s, payload_values = self._save_gas(device, _get_float)
        elif sensor_type == 'power':
            sd, s, payload_values = self._save_power(device, _get_float)
        else:
            return Response(
                {'error': f'미지원 sensor_type: {sensor_type}'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # ═══════════════════════════════════════════════════
        # 공통: Device 상태 갱신 + WS push
        # ═══════════════════════════════════════════════════
        device.status = s
        device.save(update_fields=['status', 'last_value'])

        publish_sensor_update({
            "device_id":   device.device_id,
            "sensor_type": sensor_type,
            "status":      s,
            "values":      payload_values,
            "timestamp":   sd.timestamp.isoformat(),
        })

        # ═══════════════════════════════════════════════════
        # 임계치 알람 — 백그라운드 스레드로 실행
        # evaluate_sensor() 는 Redis 상태 전이 + 조건부 DB 알람 생성을 담당.
        # 메인 흐름을 막지 않도록 daemon 스레드로 분리.
        # ═══════════════════════════════════════════════════
        import threading
        detail = _gas_detail(payload_values) if sensor_type == 'gas' else ''
        threading.Thread(
            target=_run_evaluate_sensor,
            args=(device.device_id, sensor_type, s, detail),
            daemon=True,
        ).start()

        # ═══════════════════════════════════════════════════
        # AI 파이프라인 — 백그라운드 스레드로 실행
        # request payload의 sensor_type AND DB의 device.sensor_type 둘 다 gas여야 실행
        # → DB 데이터 오류(예: electric 장치가 gas로 잘못 등록)로 인한 오탐 방지
        # ═══════════════════════════════════════════════════
        if sensor_type == 'gas' and device.sensor_type == 'gas':
            threading.Thread(
                target=_run_ai_pipeline,
                args=(device.device_id, payload_values),
                daemon=True,
            ).start()
        elif sensor_type == 'power' and device.sensor_type == 'power':
            threading.Thread(
                target=_run_power_ai_pipeline,
                args=(device.device_id, payload_values),
                daemon=True,
            ).start()

        return Response(
            {'id': sd.id, 'status': s},
            status=http_status.HTTP_201_CREATED,
        )

    # ─── 가스 저장 ───
    def _save_gas(self, device, _get_float):
        gas = {
            'co':  _get_float('co'),
            'h2s': _get_float('h2s'),
            'co2': _get_float('co2'),
            'o2':  _get_float('o2'),
            'no2': _get_float('no2'),
            'so2': _get_float('so2'),
            'o3':  _get_float('o3'),
            'nh3': _get_float('nh3'),
            'voc': _get_float('voc'),
        }
        # 판정 — alerts.services 단일 출처
        s = classify_gas(gas)

        sd = SensorData.objects.create(
            device=device,
            co=gas['co'],   h2s=gas['h2s'], co2=gas['co2'], o2=gas['o2'],
            no2=gas['no2'], so2=gas['so2'], o3=gas['o3'],
            nh3=gas['nh3'], voc=gas['voc'],
            status=s,
        )
        # 지도 마커용 대표값: CO
        if gas['co'] is not None:
            device.last_value = gas['co']
        return sd, s, gas

    # ─── 전력 저장 ───
    def _save_power(self, device, _get_float):
        power = {
            'current': _get_float('current'),
            'voltage': _get_float('voltage'),
            'watt':    _get_float('watt'),
        }
        # 판정 — 동적 24h 중앙값 기반 (device_id 전달 필수)
        s = classify_power(power, device.device_id)

        sd = SensorData.objects.create(
            device=device,
            current=power['current'],
            voltage=power['voltage'],
            watt=power['watt'],
            status=s,
        )
        # 지도 마커용 대표값: watt
        if power['watt'] is not None:
            device.last_value = power['watt']
        return sd, s, power


# ═══════════════════════════════════════════════════════════
# 임계치 알람 헬퍼
# ═══════════════════════════════════════════════════════════

def _gas_detail(gas: dict) -> str:
    """임계치를 초과한 가스 중 가장 심각한 것을 'KEY:값' 형태로 반환."""
    for key, val in gas.items():
        if val is None:
            continue
        t = GAS_THRESHOLDS.get(key)
        if t and float(val) >= t['danger']:
            return f'{key.upper()}:{float(val):.2f}'
    for key, val in gas.items():
        if val is None:
            continue
        t = GAS_THRESHOLDS.get(key)
        if t and float(val) >= t['caution']:
            return f'{key.upper()}:{float(val):.2f}'
    return ''


def _run_evaluate_sensor(device_id: str, sensor_type: str,
                         observed_status: str, detail: str) -> None:
    """백그라운드에서 임계치 상태 전이 판정 + 알람 생성."""
    try:
        evaluate_sensor(device_id, sensor_type, observed_status, detail)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "[evaluate_sensor] %s error: %s", device_id, exc
        )
    finally:
        from django.db import close_old_connections
        close_old_connections()


# ═══════════════════════════════════════════════════════════
# AI 파이프라인 헬퍼
# ═══════════════════════════════════════════════════════════

import threading as _threading
import time as _time

# 동시 실행 AI 파이프라인 최대 2개 — 초과 시 해당 틱 스킵
# GIL 충돌(tick 30 thundering herd) 방지
_AI_SEMAPHORE = _threading.Semaphore(2)

# AI 상태 → Alarm 타입 + 기본 레벨 매핑
# [레벨 설계 원칙]
#   - 임계치 초과(sensor_danger): danger  — 이미 발생한 사실
#   - AI 탐지(ML_ANOMALY):        danger  — 가장 신뢰도 높은 AI 판정
#   - 급변·드리프트·통계이상:     caution — 추세 경고, 아직 임계치 미달
#   - 예측(PREDICTIVE_*):         caution — 아직 일어나지 않은 미래
_AI_ALARM_MAP = {
    "ML_ANOMALY":         ("ai_ml_anomaly",         "danger"),
    "ANOMALY_WARNING":    ("ai_anomaly_warning",     "caution"),
    "TREND_SHIFT":        ("ai_trend_shift",         "caution"),   # info→caution: 급변은 주의 수준
    "PREDICTIVE_ALERT":   ("ai_predictive_alert",    "caution"),   # danger→caution: 예측은 한 단계 낮게
    "PREDICTIVE_WARNING": ("ai_predictive_warning",  "caution"),
    "DRIFT_ALERT":        ("ai_drift_alert",         "caution"),
}

# ─── 에스컬레이션 ───────────────────────────────────────────
# 같은 알람이 ESCALATION_WINDOW_SEC 안에 ESCALATION_THRESHOLD 회
# 이상 반복되면 레벨을 한 단계 올림 (caution→danger, danger→critical).
# 5분간 조용해지면 카운트 자동 리셋.
ESCALATION_THRESHOLD = 3
ESCALATION_WINDOW_SEC = 300

_LEVEL_ORDER = ["info", "caution", "danger", "critical"]
_esc_lock = _threading.Lock()
_esc_state: dict = {}  # "device:metric:alarm_type" → {"count": int, "last_seen": float}

# 알람 재발행 억제 기간 (초)
# 가스 AI 알람: threshold 알람이 실제 위험을 별도로 커버하므로 300s로 늘려 알람 피로 감소
# 전력 AI 알람: threshold 없는 danger 알람이 존재하므로 60s 유지
# 에스컬레이션 발생 시: 레벨 상향이므로 항상 짧은 쿨다운으로 통과 (위험 상향 누락 방지)
_GAS_COOLDOWN_SEC  = 300
_BASE_COOLDOWN_SEC = 60

# ── 위험 임박 우선 통과 기준 ─────────────────────────────────
# 300s 가스 쿨다운 중이라도 아래 조건 중 하나를 만족하면 60s 간격으로 즉시 재알람.
_BYPASS_DETECTOR_MIN = 3    # 탐지기 N개 이상 동시 발화
_BYPASS_VALUE_RATIO  = 2.0  # 마지막 알람 이후 농도 N배 이상 급등 (가연가스 전용)
_BYPASS_DANGER_RATIO = 0.8  # 위험 임계치의 N% 이상 도달
# O2 임계치는 alerts.services 단일 출처 (O2_DANGER_LOW, O2_CAUTION_LOW import)

# 마지막 알람 발행 시점의 측정값 저장 (조건 3 판단용, 재시작 시 초기화)
_last_alarm_values: dict = {}  # "device_id:metric" → {"value": float, "ts": float}
_lav_lock = _threading.Lock()


def _is_danger_imminent(
    device_id: str,
    metric: str,
    current_value: float,
    detector_count: int,
) -> bool:
    """
    쿨다운 중 위험 임박 여부 판단.
    True 반환 시 300s 가스 쿨다운을 60s로 단축하여 즉시 재알람.

    [조건 1] 탐지기 3개 이상 동시 발화 — 앙상블 고신뢰, 실제 이상 가능성 높음
    [조건 2] 위험 임계치 80% 이상 도달 — 임계치 직전, 조기 대피 필요
    [조건 3] 마지막 알람 이후 농도 2배 이상 급등 — 상황 급격히 악화 중 (가연가스 전용)
    """
    if current_value <= 0:
        return False

    # 조건 1: 앙상블 고신뢰
    if detector_count >= _BYPASS_DETECTOR_MIN:
        return True

    # 조건 2: 위험 임계치 근접
    if metric == 'o2':
        # O2: caution(18%)→danger(16%) 구간의 80% 이상 진행 = 16.4% 이하
        threshold = O2_DANGER_LOW + (O2_CAUTION_LOW - O2_DANGER_LOW) * (1 - _BYPASS_DANGER_RATIO)
        if current_value <= threshold:
            return True
    else:
        t = GAS_THRESHOLDS.get(metric)
        if t and current_value >= t['danger'] * _BYPASS_DANGER_RATIO:
            return True

    # 조건 3: 마지막 알람 이후 2배 이상 급등 (O2 제외 — 방향이 반대)
    if metric != 'o2':
        with _lav_lock:
            last = _last_alarm_values.get(f"{device_id}:{metric}")
        if last and last['value'] > 0 and current_value / last['value'] >= _BYPASS_VALUE_RATIO:
            return True

    return False


def _escalate_level(device_id: str, metric: str, alarm_type: str, base_level: str) -> tuple:
    """
    에스컬레이션 카운트를 갱신하고 (최종 레벨, 누적 횟수)를 반환.

    - ESCALATION_WINDOW_SEC 내 재발 → count 증가
    - 그 이상 침묵 → count 1로 리셋
    - count >= ESCALATION_THRESHOLD → 레벨 1단계 업
    """
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

# 가스 9종 / 전력 3종 메트릭
_GAS_METRICS   = ['co', 'h2s', 'co2', 'o2', 'no2', 'so2', 'o3', 'nh3', 'voc']
_POWER_METRICS = ['current', 'voltage', 'watt']

# 상관관계 분석 상수
_COMBUSTIBLE_GAS       = {'co', 'h2s', 'no2', 'so2', 'o3', 'nh3', 'voc'}  # O2 제외 가연/유해 가스
_O2_DISPLACEMENT_TH    = 19.5   # O2 이 이하면 치환 의심 (정상: 20.9%)
_MULTI_GAS_ANOMALY_MIN = 3      # 동시 이상 탐지 최소 종류

# 전력-가스 교차 상관관계 — 2분 이내 교차 이상 시 전기 화재 의심
_CROSS_WINDOW_SEC = 120
_cross_lock = _threading.Lock()
_recent_gas_anomalies: dict = {}    # device_id → {"metrics": [...], "ts": float}
_recent_power_anomalies: dict = {}  # device_id → {"metrics": [...], "ts": float}


def _evict_stale_cross_events() -> None:
    """만료된 교차 상관 항목 제거 — lock 보유 중에 호출."""
    now = _time.time()
    stale = [k for k, v in _recent_gas_anomalies.items() if now - v["ts"] > _CROSS_WINDOW_SEC]
    for k in stale:
        del _recent_gas_anomalies[k]
    stale = [k for k, v in _recent_power_anomalies.items() if now - v["ts"] > _CROSS_WINDOW_SEC]
    for k in stale:
        del _recent_power_anomalies[k]


def _record_gas_anomaly(device_id: str, metrics: list) -> None:
    with _cross_lock:
        _recent_gas_anomalies[device_id] = {"metrics": list(metrics), "ts": _time.time()}
        _evict_stale_cross_events()


def _record_power_anomaly(device_id: str, metrics: list) -> None:
    with _cross_lock:
        _recent_power_anomalies[device_id] = {"metrics": list(metrics), "ts": _time.time()}
        _evict_stale_cross_events()


def _get_recent_gas_events() -> list:
    """최근 _CROSS_WINDOW_SEC 내 가스 이상 감지 목록 반환."""
    now = _time.time()
    with _cross_lock:
        return [
            {"device_id": dev, "metrics": e["metrics"]}
            for dev, e in _recent_gas_anomalies.items()
            if now - e["ts"] <= _CROSS_WINDOW_SEC
        ]


def _run_ai_pipeline(device_id: str, gas_values: dict) -> None:
    """
    9종 가스 각각에 대해 AI 파이프라인을 실행하고,
    이상이 감지된 경우 Alarm 을 생성 + WS 발행.

    세마포어로 동시 실행 수 제한 — 획득 실패 시 이번 틱 스킵.
    중복 억제: 동일 device_id + metric + alarm_type 조합은
    최근 60초 내 이미 있으면 새로 생성하지 않음.
    """
    acquired = _AI_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        return  # 현재 2개 이상 실행 중 → 이번 틱 스킵

    try:
        _run_ai_pipeline_inner(device_id, gas_values)
    finally:
        _AI_SEMAPHORE.release()


def _run_ai_pipeline_inner(device_id: str, gas_values: dict) -> None:
    anomaly_metrics = []  # 이번 틱에 AI가 이상 감지한 메트릭 목록

    for metric in _GAS_METRICS:
        value = gas_values.get(metric)
        if value is None:
            continue

        result = ai_pipeline.analyze(device_id, metric, value)

        current = result["current_status"]
        if current != "NORMAL":
            _maybe_create_alarm(device_id, metric, current, result, is_predictive=False)
            anomaly_metrics.append(metric)

        predictive = result["predictive_status"]
        if predictive != "NORMAL":
            _maybe_create_alarm(device_id, metric, predictive, result, is_predictive=True)

        # 예측값을 차트용으로 발행 (ARIMA 모델 준비 완료 시에만)
        arima = result["details"].get("arima", {})
        if arima.get("model_ready") and arima.get("predicted_values"):
            publish_ai_prediction({
                "device_id": device_id,
                "metric": metric,
                "predicted_values": arima["predicted_values"],
                "steps": arima["steps"],
            })

    # 가스 이상 기록 (전력-가스 교차 상관관계용)
    if anomaly_metrics:
        _record_gas_anomaly(device_id, anomaly_metrics)

    # 동일 센서 내 상관관계 분석 — 2종 이상 이상 감지 시 실행
    if len(anomaly_metrics) >= 2:
        _check_gas_correlation(device_id, anomaly_metrics, gas_values)

    # 공간 확산 탐지 — 인근 센서 상승 추세 확인 (백그라운드)
    if anomaly_metrics:
        _threading.Thread(
            target=_check_spatial_diffusion,
            args=(device_id, list(anomaly_metrics)),
            daemon=True,
        ).start()


def _maybe_create_alarm(
    device_id: str,
    metric: str,
    ai_status: str,
    result: dict,
    is_predictive: bool,
) -> None:
    """중복 억제 + 에스컬레이션 후 Alarm 생성 및 WS 발행."""
    from django.utils import timezone
    from datetime import timedelta

    alarm_type, base_level = _AI_ALARM_MAP.get(ai_status, (None, None))
    if alarm_type is None:
        return

    now = timezone.now()

    # 에스컬레이션 카운트: 60s 주기로만 갱신
    # 300s 가스 쿨다운 중에도 60s마다 카운트가 쌓여 2분 지속 시 에스컬레이션 가능
    base_cutoff = now - timedelta(seconds=_BASE_COOLDOWN_SEC)
    recent_60s = Alarm.objects.filter(
        device_id=device_id,
        sensor_type=metric,
        alarm_type=alarm_type,
        created_at__gte=base_cutoff,
    ).exists()

    final_level = base_level
    escalated = False
    if not recent_60s:
        # 60s가 지났을 때만 카운트 갱신 → 매 틱 증가 방지
        final_level, esc_count = _escalate_level(device_id, metric, alarm_type, base_level)
        escalated = final_level != base_level

    # 위험 임박 우선 통과 여부 (예측 알람·전력·에스컬레이션 이미 통과는 제외)
    current_value = result.get("current_value") or 0.0
    bypass = (
        not is_predictive
        and not escalated
        and metric in _GAS_METRICS
        and _is_danger_imminent(device_id, metric, current_value, result.get("detector_count", 0))
    )

    # ── 쿨다운 억제 (3단계 우선순위) ──────────────────────────
    # 1) 에스컬레이션: recent_60s=False 이미 보장 → 바로 통과
    # 2) 위험 임박  : 300s → 60s 단축 (스팸 방지 최소 간격 유지)
    # 3) 일반       : 메트릭별 쿨다운 (가스=300s, 전력=60s)
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
            if recent_60s:
                return

    # 메시지 생성
    if is_predictive:
        pred = result["details"]["arima"]
        msg = (
            f"[AI예측] {device_id} / {metric.upper()} "
            f"— {FORECAST_STEPS_LABEL}후 {pred['predicted_max']} 도달 예상 ({ai_status})"
        )
    elif ai_status == "DRIFT_ALERT":
        cusum = result["details"]["cusum"]
        direction = cusum["direction"]
        direction_label = "서서히 상승 중" if direction == "up" else "서서히 하강 중"
        baseline = cusum.get("mu")
        if metric in _POWER_METRICS:
            concern = "과부하 의심" if direction == "up" else "전압 강하 의심"
        else:
            concern = "누출 의심" if direction == "up" else "산소 결핍 의심"
        msg = (
            f"[AI드리프트] {device_id} / {metric.upper()} "
            f"— {direction_label} (기준값 {baseline}, {concern})"
        )
    else:
        msg = f"[AI탐지] {device_id} / {metric.upper()} — {ai_status} (윈도우 {result['window_size']}개)"

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
    )

    # 마지막 알람 측정값 저장 (다음 bypass 조건 3 판단용)
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


FORECAST_STEPS_LABEL = "10틱"


# ═══════════════════════════════════════════════════════════
# 전력 AI 파이프라인
# ═══════════════════════════════════════════════════════════

def _run_power_ai_pipeline(device_id: str, power_values: dict) -> None:
    """
    전력 3종(current/voltage/watt) AI 파이프라인.

    가스 파이프라인과 동일한 세마포어 공유 — 총 동시 실행 2개 제한.
    전력 특화 동작:
      - ARIMA: 임계치 없음(None) → 이상 탐지 전용(threshold 비교 생략)
      - CUSUM: self-calibrating → 기준값 대비 상승/하락 드리프트 감지
      - IsolationForest: 세 메트릭의 사용 패턴 학습 → 이상 전력 소비 탐지
    """
    acquired = _AI_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        return
    try:
        _run_power_ai_pipeline_inner(device_id, power_values)
    finally:
        _AI_SEMAPHORE.release()


def _run_power_ai_pipeline_inner(device_id: str, power_values: dict) -> None:
    power_anomaly_metrics = []

    for metric in _POWER_METRICS:
        value = power_values.get(metric)
        if value is None:
            continue

        result = ai_pipeline.analyze(device_id, metric, value, sensor_type='power')

        current = result["current_status"]
        if current != "NORMAL":
            _maybe_create_alarm(device_id, metric, current, result, is_predictive=False)
            power_anomaly_metrics.append((metric, current))

        predictive = result["predictive_status"]
        if predictive != "NORMAL":
            _maybe_create_alarm(device_id, metric, predictive, result, is_predictive=True)

        # 전류 예측값을 차트용으로 발행 (ARIMA 모델 준비 완료 시에만)
        if metric == 'current':
            arima = result["details"].get("arima", {})
            if arima.get("model_ready") and arima.get("predicted_values"):
                publish_ai_prediction({
                    "device_id": device_id,
                    "metric": "current",
                    "predicted_values": arima["predicted_values"],
                    "steps": arima["steps"],
                })

    # 전력-가스 교차 상관관계 분석
    if power_anomaly_metrics:
        _record_power_anomaly(device_id, [m for m, _ in power_anomaly_metrics])
        recent_gas = _get_recent_gas_events()
        if recent_gas:
            _check_power_gas_correlation(device_id, power_anomaly_metrics, recent_gas)


# ═══════════════════════════════════════════════════════════
# 가스 상관관계 분석
# ═══════════════════════════════════════════════════════════

def _check_gas_correlation(
    device_id: str,
    anomaly_metrics: list,
    gas_values: dict,
) -> None:
    """
    가스 센서 간 상관관계 기반 복합 위험 판정.

    규칙 1 — O2 치환 감지:
      O2 < 19.5% AND 가연/유해 가스 이상 동시 감지
      → 가스가 산소를 밀어내는 치환 현상 의심 (즉시 대피 필요)

    규칙 2 — 복합 가스 이상:
      3종 이상 가스 동시 AI 이상 → 단순 노이즈가 아닌 실제 오염 가능성 높음

    각 규칙은 tag로 60초 중복 억제.
    """
    o2_val = gas_values.get('o2')

    # 규칙 1: O2 치환
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

    # 규칙 2: 복합 가스 이상
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
# 공간 확산 탐지 — 인근 센서 상승 추세 확인 (ai_correlation / diffusion)
# ═══════════════════════════════════════════════════════════

# 인근 센서 탐색 반경 (Device.x/y 좌표 단위)
_DIFFUSION_RADIUS    = 500.0
# 추세 비교에 사용할 절반 윈도우 크기 (앞 N개 평균 vs 뒤 N개 평균)
_DIFFUSION_HALF      = 5
# 인근 센서 상승 판정 비율 — 뒤쪽 평균이 앞쪽 평균보다 이 비율 이상 높으면 상승 중
_DIFFUSION_RISE_RATE = 0.08   # 8%


def _is_rising(values: list[float]) -> bool:
    """
    슬라이딩 윈도우 값 목록에서 최근 상승 추세 여부 판정.
    앞 _DIFFUSION_HALF 개 평균 vs 뒤 _DIFFUSION_HALF 개 평균을 비교.
    """
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
    """
    이상 탐지된 센서 인근 가스 센서들의 상승 추세를 확인해
    가스 확산 패턴이 감지되면 ai_correlation (diffusion) 알람 발생.

    동작:
      1. 이상 탐지 센서 좌표 조회
      2. _DIFFUSION_RADIUS 이내 다른 활성 가스 센서 목록
      3. 각 인근 센서의 슬라이딩 윈도우에서 이상 메트릭 상승 추세 확인
      4. 2개 이상 인근 센서에서 상승 → diffusion 알람
    """
    try:
        from devices.models import Device
        from ml_engine.sliding_window import get_values as _get_win
        import math

        try:
            src = Device.objects.get(device_id=device_id, is_active=True)
        except Device.DoesNotExist:
            return

        # 인근 가스 센서 (자기 자신 제외)
        candidates = Device.objects.filter(
            sensor_type='gas', is_active=True
        ).exclude(device_id=device_id)

        rising_neighbors = []
        for dev in candidates:
            dist = math.hypot(dev.x - src.x, dev.y - src.y)
            if dist > _DIFFUSION_RADIUS:
                continue

            # 이상 감지된 메트릭 중 하나라도 상승 중이면 포함
            for metric in anomaly_metrics:
                if metric == 'o2':   # O2 는 하락이 위험 → 확산 방향이 다름
                    continue
                vals = _get_win(dev.device_id, metric)
                if _is_rising(vals):
                    rising_neighbors.append((dev.device_id, metric, round(dist, 1)))
                    break   # 한 메트릭만 확인해도 충분

        if len(rising_neighbors) >= 2:
            neighbor_desc = ', '.join(
                f"{did}({m})" for did, m, _ in rising_neighbors
            )
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
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("[diffusion] %s: %s", device_id, exc)
    finally:
        from django.db import close_old_connections
        close_old_connections()


def _check_power_gas_correlation(
    power_device_id: str,
    power_anomalies: list,   # [(metric, status), ...]
    recent_gas_events: list, # [{"device_id": str, "metrics": [...]}, ...]
) -> None:
    """
    전력-가스 교차 상관관계.

    규칙: 전류(current) 또는 전력(watt) AI 이상 + 최근 2분 내 가스 이상
    → 전기 화재 의심 (전기 스파크 → 가스 점화 가능성)

    전류·전력만 대상으로 삼는 이유:
      voltage 단독 이상은 전력망 문제로 가스와 무관할 수 있음.
      current/watt 급등은 과열·스파크 가능성이 높음.
    """
    concern_metrics = [
        m for m, status in power_anomalies
        if m in ('current', 'watt') and status in ('ML_ANOMALY', 'DRIFT_ALERT')
    ]
    if not concern_metrics:
        return

    for gas_event in recent_gas_events:
        gas_device_id = gas_event["device_id"]
        gas_metrics   = gas_event["metrics"]
        _create_correlation_alarm(
            device_id=power_device_id,
            alarm_level='danger',
            message=(
                f"[AI상관] 전력({power_device_id}) "
                f"{'/'.join(m.upper() for m in concern_metrics)} 이상 "
                f"+ 가스({gas_device_id}) "
                f"{'/'.join(m.upper() for m in gas_metrics)} 이상 동시 감지 "
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
    """상관관계 알람 생성 (60초 중복 억제, sensor_type=tag 로 구분)."""
    from django.utils import timezone
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(seconds=60)
    if Alarm.objects.filter(
        device_id=device_id,
        alarm_type='ai_correlation',
        sensor_type=tag,
        created_at__gte=cutoff,
    ).exists():
        return

    alarm = Alarm.objects.create(
        alarm_type='ai_correlation',
        alarm_level=alarm_level,
        device_id=device_id,
        sensor_type=tag,
        message=message,
    )

    publish_alarm({
        "alarm_id":    alarm.id,
        "alarm_type":  'ai_correlation',
        "alarm_level": alarm_level,
        "device_id":   device_id,
        "message":     message,
    })