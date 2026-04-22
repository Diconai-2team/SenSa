"""
alerts/services.py
알람 생성 로직 — 지오펜스 진입, 센서 이상, 복합 위험 알람 생성

변경점 (v2):
  - _find_sensor_geofence: Device.geofence FK 우선 사용 (좌표 fallback 유지)
  - latest_worker_locations: 각 worker의 최신 위치 조회 헬퍼 추가
  - workers_inside_geofence: 지오펜스 내부 worker 목록
  - create_sensor_alarm: 지오펜스 내 worker에게 자동으로 combined 알람 전파
"""
import statistics
import time
from datetime import timedelta

from django.db.models import Subquery, OuterRef
from django.utils import timezone

from geofence.models import GeoFence
from geofence.services import point_in_polygon
from .models import Alarm

# ── 중복 알람 방지 캐시 (메모리, 30초 쿨다운) ──────────────────────
_alarm_cache: dict[str, float] = {}
_COOLDOWN = 30  # 초


def _is_duplicate(key: str) -> bool:
    now = time.time()
    last = _alarm_cache.get(key)
    if last and now - last < _COOLDOWN:
        return True
    _alarm_cache[key] = now
    return False

# ── 실제 센서 스펙 기준 임계치 ──────────────────────────────────────
# 출처: (주)디코나이 센서별 데이터 구조 및 임계치 정의서
GAS_THRESHOLDS = {
    'co':  {'caution': 25,    'danger': 200  },
    'h2s': {'caution': 10,    'danger': 15   },
    'co2': {'caution': 1000,  'danger': 5000 },
    'no2': {'caution': 3,     'danger': 5    },
    'so2': {'caution': 2,     'danger': 5    },
    'o3':  {'caution': 0.06,  'danger': 0.12 },
    'nh3': {'caution': 25,    'danger': 35   },
    'voc': {'caution': 0.5,   'danger': 1.0  },
    # o2는 구간형 — 아래 classify_gas() 참고
}


def classify_gas(gas: dict) -> str:
    """
    가스 측정값 딕셔너리를 받아 normal / caution / danger 반환.
    O2는 구간형 판별 (18~23.5 정상 / 16~18 주의 / <16 위험).
    나머지는 단순 초과 비교.
    """
    worst = 'normal'
    for key, val in gas.items():
        if val is None:
            continue
        if key == 'o2':
            if float(val) < 16:
                return 'danger'
            if float(val) < 18:
                worst = 'caution'
            continue
        t = GAS_THRESHOLDS.get(key)
        if not t:
            continue
        val = float(val)
        if val >= t['danger']:
            return 'danger'
        if val >= t['caution'] and worst == 'normal':
            worst = 'caution'
    return worst


# 전력 동적 임계치 계수
# 산업용 설비 기준: 정격 = 평상시 평균 × 1.5배 여유
# 과부하 주의: 정격 × 1.1 = 평균 × 1.65
# 과부하 위험: 정격 × 1.5 = 평균 × 2.25
_POWER_RATED_RATIO   = 1.5
_POWER_CAUTION_MULT  = _POWER_RATED_RATIO * 1.1   # 1.65
_POWER_DANGER_MULT   = _POWER_RATED_RATIO * 1.5   # 2.25
_POWER_MIN_SAMPLES   = 1440                        # 동적 판정 최소 샘플 (1분 × 1440 = 24시간)


def _get_24h_avg_watt(device_id: str) -> float | None:
    """
    최근 24시간 전력(watt) 측정값의 중앙값 반환.
    중앙값 사용 이유: 기동전류(정격의 5~8배) 같은 순간 스파이크에 강건함.
    샘플이 부족하면 None 반환 → 고정 임계치 fallback.
    """
    from devices.models import SensorData
    cutoff = timezone.now() - timedelta(hours=24)
    values = list(
        SensorData.objects.filter(
            device__device_id=device_id,
            timestamp__gte=cutoff,
            watt__isnull=False,
        ).values_list('watt', flat=True)
    )
    if len(values) < _POWER_MIN_SAMPLES:
        return None
    return statistics.median(values)


def classify_power(power: dict, device_id: str = '') -> str:
    """
    전력 측정값 동적 임계치 분류.

    1순위: 최근 24시간 중앙값 기반 동적 판정
      - 평균 × 1.65 초과 → caution (정격의 1.1배 초과)
      - 평균 × 2.25 초과 → danger  (정격의 1.5배 초과)
    2순위(fallback): 고정 임계치 (초기 데이터 부족 시)
    전압 이상(200V 미만 / 240V 초과)은 항상 위험으로 고정.
    """
    watt = float(power.get('watt', 0))
    vol  = float(power.get('voltage', 220))
    cur  = float(power.get('current', 0))

    # 전압 이상 — 설비 안전 기준, 항상 고정
    if vol < 200 or vol > 240:
        return 'danger'

    # 동적 판정 (24시간 누적 데이터 있을 때)
    if device_id:
        avg = _get_24h_avg_watt(device_id)
        if avg and avg > 0:
            if watt > avg * _POWER_DANGER_MULT:
                return 'danger'
            if watt > avg * _POWER_CAUTION_MULT:
                return 'caution'
            return 'normal'

    # fallback — 고정 임계치
    if cur >= 25 or watt >= 4500:
        return 'danger'
    if cur >= 15 or watt >= 3000:
        return 'caution'
    return 'normal'


# ─────────────────────────────────────────────────────────
# 센서 → 지오펜스 매핑
# v2: Device.geofence FK 우선 사용 (좌표 계산 불필요)
#     FK가 null인 경우에만 좌표 기반 fallback
# ─────────────────────────────────────────────────────────
def _find_sensor_geofence(device_id: str):
    """센서 device_id로 속한 지오펜스 반환. 없으면 None."""
    try:
        from devices.models import Device  # 순환 import 방지
        device = Device.objects.select_related('geofence').get(device_id=device_id)
    except Exception:
        return None

    # 1순위: 명시적으로 지정된 FK
    if device.geofence and device.geofence.is_active:
        return device.geofence

    # 2순위 (fallback): 좌표 기반 자동 판정 (FK 미지정 센서용)
    for fence in GeoFence.objects.filter(is_active=True):
        if fence.polygon and len(fence.polygon) >= 3:
            if point_in_polygon(device.x, device.y, fence.polygon):
                return fence
    return None


# ─────────────────────────────────────────────────────────
# Worker 위치 헬퍼
# ─────────────────────────────────────────────────────────
def latest_worker_locations():
    """
    각 활성 worker의 최신 WorkerLocation을 (worker, x, y)로 yield.
    WorkerLocation은 1초마다 쌓이므로 worker별 최신 1건만 필요.
    """
    from workers.models import Worker, WorkerLocation  # 순환 import 방지

    latest_loc_sq = WorkerLocation.objects.filter(
        worker=OuterRef('pk')
    ).order_by('-timestamp').values('id')[:1]

    workers = Worker.objects.filter(is_active=True).annotate(
        latest_loc_id=Subquery(latest_loc_sq)
    )

    loc_ids = [w.latest_loc_id for w in workers if w.latest_loc_id]
    locations = {
        loc.id: loc
        for loc in WorkerLocation.objects.filter(id__in=loc_ids)
    }

    for w in workers:
        loc = locations.get(w.latest_loc_id)
        if loc:
            yield w, loc.x, loc.y


def workers_inside_geofence(geofence: GeoFence) -> list:
    """
    geofence polygon 내부에 최신 위치가 있는 worker 목록 반환.
    각 원소: (worker, x, y) 튜플
    """
    if not geofence.polygon or len(geofence.polygon) < 3:
        return []
    result = []
    for worker, x, y in latest_worker_locations():
        if point_in_polygon(x, y, geofence.polygon):
            result.append((worker, x, y))
    return result


# ─────────────────────────────────────────────────────────
# 지오펜스 진입 알람 (기존 유지)
# ─────────────────────────────────────────────────────────
def check_worker_in_geofences(worker_id: str, worker_name: str,
                               x: float, y: float) -> list:
    """
    작업자 좌표(x, y)가 어떤 지오펜스 안에 있는지 확인.

    v3 수정: 쿨다운이 결과 목록 자체를 막던 버그 수정.
      - worker가 지오펜스 안에 있다는 "사실"은 항상 results에 포함 (combined 매칭용)
      - "Alarm 레코드 생성"만 30초 쿨다운 적용
    """
    results = []
    fences = GeoFence.objects.filter(is_active=True)

    for fence in fences:
        if not fence.polygon or len(fence.polygon) < 3:
            continue

        if not point_in_polygon(x, y, fence.polygon):
            continue

        level = _zone_to_alarm_level(fence.zone_type)
        msg = f"{worker_name}이(가) [{fence.name}]에 진입했습니다. (zone: {fence.zone_type})"

        entry = {
            "geofence_id": fence.id,
            "geofence_name": fence.name,
            "zone_type": fence.zone_type,
            "alarm_level": level,
            "message": msg,
        }

        # Alarm 레코드 생성만 쿨다운 적용 (중복 알림 방지)
        # workers_in_fences 매칭 용도의 "있다는 사실"은 항상 반환
        key = f"geofence_enter-{worker_id}-{fence.id}"
        if not _is_duplicate(key):
            alarm = Alarm.objects.create(
                alarm_type='geofence_enter',
                alarm_level=level,
                worker_id=worker_id,
                worker_name=worker_name,
                worker_x=x,
                worker_y=y,
                geofence=fence,
                message=msg,
            )
            entry["alarm_id"] = alarm.id

        results.append(entry)

    return results


# ─────────────────────────────────────────────────────────
# 센서 알람 + worker 전파 (핵심 변경)
# ─────────────────────────────────────────────────────────
def create_sensor_alarm(device_id: str, sensor_type: str,
                        gas: dict = None, power: dict = None) -> dict | None:
    """
    raw 센서값을 받아 서버가 직접 임계치 판별 후 알람 생성.
    normal이면 None 반환.

    v2 추가:
      센서가 속한 지오펜스 내에 worker가 있으면
      → 각 worker에게 별도의 combined 알람도 생성
    """
    if sensor_type == 'gas' and gas:
        status = classify_gas(gas)
        detail = ', '.join(f"{k.upper()}:{v}" for k, v in gas.items() if v is not None)
    elif sensor_type == 'power' and power:
        status = classify_power(power, device_id)
        cur = float(power.get('current', 0))
        vol = float(power.get('voltage', 220))
        wat = float(power.get('watt', 0))
        detail = f"전류:{cur}A 전압:{vol}V 전력:{wat}W"
    else:
        return None

    if status == 'normal':
        return None

    key = f"sensor-{device_id}-{status}"
    if _is_duplicate(key):
        return None

    alarm_type = 'sensor_caution' if status == 'caution' else 'sensor_danger'
    alarm_level = status
    msg = f"센서 [{device_id}] {status.upper()} 상태 감지. {detail}"

    fence = _find_sensor_geofence(device_id)

    # 1) 센서 단독 알람 (항상 1건 생성)
    alarm = Alarm.objects.create(
        alarm_type=alarm_type,
        alarm_level=alarm_level,
        device_id=device_id,
        sensor_type=sensor_type,
        geofence=fence,
        message=msg,
    )

    # 2) 지오펜스 안에 worker가 있으면 각자에게 combined 알람 전파
    propagated = []
    if fence is not None:
        for worker, wx, wy in workers_inside_geofence(fence):
            combined = create_combined_alarm(
                worker_id=worker.worker_id,
                worker_name=worker.name,
                geofence=fence,
                device_id=device_id,
                sensor_status=status,
                worker_x=wx,
                worker_y=wy,
            )
            if combined:
                propagated.append(combined)

    return {
        "alarm_id": alarm.id,
        "alarm_level": alarm_level,
        "alarm_type": alarm_type,
        "status": status,
        "geofence_id": fence.id if fence else None,
        "message": msg,
        "propagated_to_workers": propagated,   # 전파된 combined 알람 목록
    }


def create_combined_alarm(worker_id: str, worker_name: str,
                          geofence: GeoFence, device_id: str,
                          sensor_status: str,
                          worker_x: float = None,
                          worker_y: float = None) -> dict:
    """
    작업자가 지오펜스 안에 있는데 + 해당 구역 센서도 위험 수치일 때.
    가장 높은 수준의 알람(critical) 생성.
    """
    key = f"combined-{worker_id}-{geofence.id}-{device_id}-{sensor_status}"
    if _is_duplicate(key):
        return {}

    msg = (
        f"[복합위험] {worker_name}이(가) [{geofence.name}]에 있는 상태에서 "
        f"센서 [{device_id}] {sensor_status.upper()} 수치 감지!"
    )

    alarm = Alarm.objects.create(
        alarm_type='combined',
        alarm_level='critical',
        worker_id=worker_id,
        worker_name=worker_name,
        worker_x=worker_x,
        worker_y=worker_y,
        geofence=geofence,
        device_id=device_id,
        message=msg,
    )

    return {
        "alarm_id": alarm.id,
        "alarm_level": "critical",
        "alarm_type": "combined",
        "worker_id": worker_id,
        "worker_name": worker_name,
        "message": msg,
    }


def _zone_to_alarm_level(zone_type: str) -> str:
    return {
        'danger': 'danger',
        'caution': 'caution',
        'restricted': 'critical',
    }.get(zone_type, 'caution')