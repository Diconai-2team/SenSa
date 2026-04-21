"""
alerts/services.py
알람 생성 로직 — 지오펜스 진입, 센서 이상, 복합 위험 알람 생성
"""
import time
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


def check_worker_in_geofences(worker_id: str, worker_name: str,
                               x: float, y: float) -> list:
    """
    작업자 좌표(x, y)가 어떤 지오펜스 안에 있는지 확인.
    진입이 감지된 지오펜스마다 알람을 생성하고 목록으로 반환.
    """
    results = []
    fences = GeoFence.objects.filter(is_active=True)

    for fence in fences:
        if not fence.polygon or len(fence.polygon) < 3:
            continue

        if point_in_polygon(x, y, fence.polygon):
            level = _zone_to_alarm_level(fence.zone_type)
            msg = f"{worker_name}이(가) [{fence.name}]에 진입했습니다. (zone: {fence.zone_type})"

            key = f"geofence_enter-{worker_id}-{fence.id}"
            if _is_duplicate(key):
                continue

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

            results.append({
                "geofence_id": fence.id,
                "geofence_name": fence.name,
                "zone_type": fence.zone_type,
                "alarm_id": alarm.id,
                "alarm_level": level,
                "message": msg,
            })

    return results


def create_sensor_alarm(device_id: str, sensor_type: str,
                        gas: dict = None, power: dict = None) -> dict | None:
    """
    raw 센서값을 받아 서버가 직접 임계치 판별 후 알람 생성.
    normal이면 None 반환.
    """
    if sensor_type == 'gas' and gas:
        status = classify_gas(gas)
        detail = ', '.join(f"{k.upper()}:{v}" for k, v in gas.items() if v is not None)
    elif sensor_type == 'power' and power:
        # 전력은 1단계 단순 비교 (4차에서 평균 기반으로 확장)
        cur = float(power.get('current', 0))
        vol = float(power.get('voltage', 220))
        wat = float(power.get('watt', 0))
        if cur >= 25 or wat >= 4500 or vol < 200 or vol > 240:
            status = 'danger'
        elif cur >= 15 or wat >= 3000 or vol < 210 or vol > 230:
            status = 'caution'
        else:
            status = 'normal'
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

    alarm = Alarm.objects.create(
        alarm_type=alarm_type,
        alarm_level=alarm_level,
        device_id=device_id,
        sensor_type=sensor_type,
        message=msg,
    )

    return {
        "alarm_id": alarm.id,
        "alarm_level": alarm_level,
        "alarm_type": alarm_type,
        "status": status,
        "message": msg,
    }


def create_combined_alarm(worker_id: str, worker_name: str,
                          geofence: GeoFence, device_id: str,
                          sensor_status: str) -> dict:
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
        geofence=geofence,
        device_id=device_id,
        message=msg,
    )

    return {
        "alarm_id": alarm.id,
        "alarm_level": "critical",
        "alarm_type": "combined",
        "message": msg,
    }


def _zone_to_alarm_level(zone_type: str) -> str:
    return {
        'danger': 'danger',
        'caution': 'caution',
        'restricted': 'critical',
    }.get(zone_type, 'caution')
