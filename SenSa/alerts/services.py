"""
alerts/services.py — 상태 전이 기반 알람 서비스

【작업자 축】evaluate_worker — 센서 기반 상태 전이
  악화: 즉시 전이 / 회복: RECOVERY_CONFIRM_TICKS 연속 후 전이
  지속 알람: SUSTAINED_ALARM_TICKS 틱 비정상 유지 시 재알림
  작업자 상태: 'safe' < 'caution' < 'danger'  (지오펜스 무관)

【지오펜스 축】check_geofence_transitions — 구역 진입/이탈 이벤트
  hazardous·restricted 구역만 1회성 알람 (지속 알람 없음)

【센서 축】evaluate_sensor — 센서 상태 전이 (60초 지속 알람)

판정 함수:
  classify_gas(gas)          — 9종 가스 worst 상태
  classify_power(power, dev) — 동적 24시간 중앙값 기반 전력 판정
"""
import statistics
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from geofence.models import GeoFence
from geofence.services import point_in_polygon
from .models import Alarm
from .state_store import (
    get_worker_snapshot, commit_state, set_pending, clear_pending,
    set_sustained_ticks, get_worker_fences, set_worker_fences,
    get_sensor_snapshot, commit_sensor_state,
    set_sensor_pending, clear_sensor_pending,
)

RECOVERY_CONFIRM_TICKS = getattr(settings, 'ALARM_RECOVERY_CONFIRM_TICKS', 3)
SUSTAINED_ALARM_TICKS  = getattr(settings, 'ALARM_SUSTAINED_TICKS', 5)
# 센서 지속 알람은 시간 기반 유지
RE_ALARM_INTERVAL_SEC  = getattr(settings, 'ALARM_RE_ALARM_INTERVAL_SEC', 60)


# ═══════════════════════════════════════════════════════════
# 가스 판정 — 9종 (Gas 전담 팀원 공식 기준)
# ═══════════════════════════════════════════════════════════
# 출처: static/js/dashboard/section_12_13_gas.js 의 TH
#       static/js/dashboard/base.js 의 GAS_TH
# 세 곳 모두 동일한 값을 써야 UI 뱃지와 서버 알람 레벨이 일치함.
#
# 철학: danger = IDLH 수준 (즉시 대피 필요)
#       caution = STEL 수준 (단시간 노출 허용 한계)
GAS_THRESHOLDS = {
    'co':  {'caution': 25,    'danger': 200  },  # ACGIH TWA / NIOSH Ceiling
    'h2s': {'caution': 10,    'danger': 50   },  # KOSHA 적정공기 / IDLH
    'co2': {'caution': 1000,  'danger': 5000 },  # 실내공기질 / TWA
    'no2': {'caution': 3,     'danger': 5    },  # 고용노동부 TWA / STEL
    'so2': {'caution': 2,     'danger': 5    },  # 고용노동부 TWA / STEL
    'o3':  {'caution': 0.05,  'danger': 0.1  },  # ACGIH TLV (light / heavy work)
    'nh3': {'caution': 25,    'danger': 50   },  # ACGIH TWA / 고노출 기준
    'voc': {'caution': 0.5,   'danger': 2.0  },  # TVOC 실내기준
    # o2 는 구간형 — classify_gas 내부 처리
}


def classify_gas(gas: dict) -> str:
    """
    9종 가스 측정값 dict 를 받아 worst 상태 반환 ('normal'/'caution'/'danger').

    O2 는 구간형 (양방향 임계) — 근거: 산업안전보건기준 제618조 + KOSHA
      < 16% 또는 >= 23.5% → danger
      < 18% 또는 > 21.5%  → caution
      18 ~ 21.5%          → normal
    나머지 8종: 단방향 (높을수록 위험)
    """
    worst = 'normal'
    for key, val in gas.items():
        if val is None:
            continue
        if key == 'o2':
            v = float(val)
            if v < 16 or v >= 23.5:
                return 'danger'
            if v < 18 or v > 21.5:
                worst = 'caution'
            continue
        t = GAS_THRESHOLDS.get(key)
        if not t:
            continue
        v = float(val)
        if v >= t['danger']:
            return 'danger'
        if v >= t['caution'] and worst == 'normal':
            worst = 'caution'
    return worst


# ═══════════════════════════════════════════════════════════
# 전력 판정 — 동적 24h 중앙값 기반 (Power 병합)
# ═══════════════════════════════════════════════════════════
# 근거:
#   산업용 설비의 전력 임계치는 설비마다 정격이 달라 고정값으로 판정하기 어려움.
#   평상시 평균의 배수로 이상 감지하는 것이 운영 표준.
#
# 중앙값(median) 사용 이유:
#   기동전류(정격의 5~8배) 같은 순간 스파이크에 강건함.
#   평균(mean) 대신 중앙값을 쓰면 극단값 영향을 받지 않음.
#
# 계수 산출:
#   산업용 설비 기준: 정격 = 평상시 평균 × 1.5 (여유율)
#   과부하 주의: 정격 × 1.1 → 평균 × 1.65
#   과부하 위험: 정격 × 1.5 → 평균 × 2.25

_POWER_RATED_RATIO   = 1.5
_POWER_CAUTION_MULT  = _POWER_RATED_RATIO * 1.1   # 1.65
_POWER_DANGER_MULT   = _POWER_RATED_RATIO * 1.5   # 2.25

# 동적 판정에 필요한 최소 샘플 수
# 개발/테스트: 초당 1건 × 180초 = 3분 치
# 운영 환경 : 초당 1건 × 86400 = 24시간 치 (상수 조정 필요)
_POWER_MIN_SAMPLES   = 180


def _get_24h_avg_watt(device_id: str) -> float | None:
    """
    최근 24시간 전력(watt) 측정값의 중앙값 반환.

    샘플이 _POWER_MIN_SAMPLES 미만이면 None 반환 → 호출자가 고정 임계치로 fallback.
    기동직후·리셋직후에 잘못된 동적 판정이 쌓이지 않도록 방어.
    """
    # 순환 import 방지 — 함수 내부 import
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

    판정 순서:
      1. 전압 이상 (200V 미만 or 240V 초과) → danger (설비 안전 기준, 항상 고정)
      2. 24h 중앙값 기반 동적 판정 (샘플 충분할 때)
      3. 고정 임계치 fallback (샘플 부족 / device_id 미지정)

    Args:
        power: {'current': float, 'voltage': float, 'watt': float}
        device_id: 동적 판정 시 24h 중앙값 조회용. 빈 값이면 fallback.
    """
    watt = float(power.get('watt', 0))
    vol  = float(power.get('voltage', 220))
    cur  = float(power.get('current', 0))

    # 1. 전압 이상 — 항상 고정
    if vol < 200 or vol > 240:
        return 'danger'

    # 2. 동적 판정
    if device_id:
        avg = _get_24h_avg_watt(device_id)
        if avg and avg > 0:
            if watt > avg * _POWER_DANGER_MULT:
                return 'danger'
            if watt > avg * _POWER_CAUTION_MULT:
                return 'caution'
            return 'normal'

    # 3. 고정 임계치 fallback
    if cur >= 25 or watt >= 4500:
        return 'danger'
    if cur >= 15 or watt >= 3000:
        return 'caution'
    return 'normal'


# ═══════════════════════════════════════════════════════════
# 지오펜스 조회 유틸
# ═══════════════════════════════════════════════════════════

def _find_containing_geofences(x: float, y: float) -> list:
    """작업자 좌표가 속한 활성 지오펜스 목록."""
    result = []
    for fence in GeoFence.objects.filter(is_active=True):
        if not fence.polygon or len(fence.polygon) < 3:
            continue
        if point_in_polygon(x, y, fence.polygon):
            result.append(fence)
    return result


def _find_sensor_geofence(device_id: str):
    """
    센서 device_id 로 속한 지오펜스 반환. 없으면 None.

    판정 순서:
      1순위: Device.geofence FK (seed_data 자동 할당 결과)
      2순위: 좌표 기반 point_in_polygon (FK 미지정 센서용 fallback)
    """
    try:
        from devices.models import Device   # 순환 import 방지
    except Exception:
        return None

    try:
        device = Device.objects.select_related('geofence').get(device_id=device_id)
    except Device.DoesNotExist:
        return None

    # 1순위: 명시적 FK
    if device.geofence and device.geofence.is_active:
        return device.geofence

    # 2순위: 좌표 기반
    for fence in GeoFence.objects.filter(is_active=True):
        if fence.polygon and len(fence.polygon) >= 3:
            if point_in_polygon(device.x, device.y, fence.polygon):
                return fence
    return None


# ═══════════════════════════════════════════════════════════
# 작업자 상태 분류 / 메시지 / 전이 매핑
# ═══════════════════════════════════════════════════════════

def _classify_sensor_state(worst_sensor_status: str) -> str:
    """센서 worst 상태 → 작업자 상태. 'normal' → 'safe'."""
    return {'danger': 'danger', 'caution': 'caution'}.get(worst_sensor_status, 'safe')


def _build_message(worker_name: str, prev: str, curr: str,
                    sensor_status: str,
                    influencing_sensors: list | None = None) -> str:
    """작업자 상태 전이별 메시지 (센서 기반)."""
    influencing_sensors = influencing_sensors or []
    
    # 센서 정보 suffix 구성
    # 예1: " (sensor_02 caution)"
    # 예2: " (sensor_01, sensor_03 caution)" — 같은 상태 여러 개
    # 예3: " (sensor_01 danger, sensor_03 caution)" — 상태 섞임
    if sensor_status != 'normal' and influencing_sensors:
        statuses = {st for _, st in influencing_sensors}
        if len(statuses) == 1:
            ids = ', '.join(sid for sid, _ in influencing_sensors)
            s = f" ({ids} {sensor_status})"
        else:
            parts = [f"{sid} {st}" for sid, st in influencing_sensors]
            s = f" ({', '.join(parts)})"
    elif sensor_status != 'normal':
        s = f" (센서 {sensor_status})"  # fallback
    else:
        s = ''
    
    if prev == 'safe' and curr == 'caution':
        return f"{worker_name} 주의 상태 진입{s}"
    if prev == 'safe' and curr == 'danger':
        return f"{worker_name} 위험 상태 진입{s}"
    if prev == 'caution' and curr == 'danger':
        return f"{worker_name} 상태 악화 — 주의→위험{s}"
    if prev == 'danger' and curr == 'caution':
        return f"{worker_name} 위험 벗어남 — 주의 수준으로 회복"
    if prev == 'danger' and curr == 'safe':
        return f"{worker_name} 안전 복귀 — 위험 상황 종료"
    if prev == 'caution' and curr == 'safe':
        return f"{worker_name} 안전 복귀 — 주의 상황 종료"
    if curr == 'danger':
        return f"{worker_name} 위험 상황 지속 중{s}"
    if curr == 'caution':
        return f"{worker_name} 주의 상황 지속 중{s}"
    return f"{worker_name} 상태 변화"


def _transition_to_type_and_level(prev: str, curr: str) -> tuple[str, str]:
    """전이 유형 → (alarm_type, alarm_level)."""
    if prev == 'safe' and curr == 'caution':
        return 'state_caution_enter', 'caution'
    if prev == 'safe' and curr == 'danger':
        return 'state_danger_enter', 'danger'
    if prev == 'caution' and curr == 'danger':
        return 'state_escalate', 'danger'
    if prev == 'danger' and curr == 'caution':
        return 'state_recover_partial', 'info'
    if prev in ('danger', 'caution') and curr == 'safe':
        return 'state_recover_safe', 'info'
    if curr == 'danger':
        return 'state_ongoing', 'danger'
    if curr == 'caution':
        return 'state_ongoing', 'caution'
    return 'state_ongoing', 'info'


def _is_escalation(prev: str, curr: str) -> bool:
    """상태 악화 여부. safe < caution < danger"""
    ladder = {'safe': 0, 'caution': 1, 'danger': 2}
    return ladder.get(curr, 0) > ladder.get(prev, 0)


# ─── 지오펜스 진입/이탈 알람 대상 zone_type ───
_ALERT_ZONE_TYPES = {'hazardous', 'restricted'}


# ═══════════════════════════════════════════════════════════
# 메인 진입점 — 작업자 1명의 알람 판정
# ═══════════════════════════════════════════════════════════

def evaluate_worker(worker_id: str, worker_name: str,
                     x: float, y: float,
                     worst_sensor_status: str = 'normal',
                     influencing_sensors: list | None = None) -> list[dict]:
    """
    작업자 1명의 상태 전이 판정 (센서 기반 전용).
    지오펜스 진입/이탈은 check_geofence_transitions 에서 별도 처리.

    악화: 즉시 전이 / 회복: RECOVERY_CONFIRM_TICKS 연속 후 전이
    지속: SUSTAINED_ALARM_TICKS 틱 비정상 유지 시 재알림
    """
    influencing_sensors = influencing_sensors or []   # ← 추가 정보 (예: ['co', 'o2']) — 메시지에 활용 가능하도록 확장 여지

    observed_state = _classify_sensor_state(worst_sensor_status)
    snap = get_worker_snapshot(worker_id)
    official_state = snap['state']
    sustained_ticks = snap['sustained_ticks']

    print(f"[DEBUG] {worker_id} ({x:.1f},{y:.1f}) "
          f"official={official_state} observed={observed_state} "
          f"pending={snap['pending_state']}({snap['pending_count']}) "
          f"sustained={sustained_ticks} sensor={worst_sensor_status}")

    # ─── 전이 확정 여부 ───
    confirmed_new_state = None

    if observed_state == official_state:
        if snap['pending_state']:
            clear_pending(worker_id)
    elif _is_escalation(official_state, observed_state):
        confirmed_new_state = observed_state
    else:
        if snap['pending_state'] == observed_state:
            new_count = snap['pending_count'] + 1
            if new_count >= RECOVERY_CONFIRM_TICKS:
                confirmed_new_state = observed_state
            else:
                set_pending(worker_id, observed_state, new_count)
        else:
            set_pending(worker_id, observed_state, 1)

    # ─── 알람 발행 여부 + sustained 카운터 ───
    should_alarm = False
    reason = None
    target_state = official_state
    new_sustained = sustained_ticks

    if confirmed_new_state is not None:
        should_alarm = True
        reason = 'transition'
        target_state = confirmed_new_state
        new_sustained = 0
    elif official_state != 'safe':
        new_sustained = sustained_ticks + 1
        if new_sustained >= SUSTAINED_ALARM_TICKS:
            should_alarm = True
            reason = 'ongoing'
            target_state = official_state
            new_sustained = 0
    else:
        new_sustained = 0

    # ─── 알람 생성 + 상태 커밋 ───
    created = []

    if should_alarm:
        alarm_type, alarm_level = _transition_to_type_and_level(official_state, target_state)
        message = _build_message(
            worker_name, official_state, target_state,
            worst_sensor_status, influencing_sensors
        )

        alarm = Alarm.objects.create(
            alarm_type=alarm_type,
            alarm_level=alarm_level,
            worker_id=worker_id,
            worker_name=worker_name,
            worker_x=x,
            worker_y=y,
            message=message,
        )

        created.append({
            'alarm_id': alarm.id,
            'alarm_type': alarm_type,
            'alarm_level': alarm_level,
            'worker_id': worker_id,
            'worker_name': worker_name,
            'message': message,
            'reason': reason,
            'state_from': official_state,
            'state_to': target_state,
        })

        print(f"[ALARM-CREATED] {worker_id} {alarm_type} level={alarm_level} reason={reason}")

        if confirmed_new_state is not None:
            commit_state(worker_id, target_state, mark_alarmed=True)
        else:
            commit_state(worker_id, official_state, mark_alarmed=True)

    set_sustained_ticks(worker_id, new_sustained)
    return created


def check_geofence_transitions(worker_id: str, worker_name: str,
                                x: float, y: float) -> list[dict]:
    """
    작업자의 지오펜스 진입/이탈 감지.
    hazardous·restricted 구역만 1회성 알람 생성.
    """
    current_fences = _find_containing_geofences(x, y)
    current_ids = {str(g.id) for g in current_fences}
    prev_ids = get_worker_fences(worker_id)

    entered_ids = current_ids - prev_ids
    exited_ids  = prev_ids - current_ids

    set_worker_fences(worker_id, current_ids)

    alarms = []

    # 진입
    for fence in current_fences:
        if str(fence.id) not in entered_ids or fence.zone_type not in _ALERT_ZONE_TYPES:
            continue
        level = 'critical' if fence.zone_type == 'restricted' else 'danger'
        suffix = ' (출입금지구역)' if fence.zone_type == 'restricted' else ' (유해구역)'
        msg = f"{worker_name} [{fence.name}] 진입{suffix}"
        alarm = Alarm.objects.create(
            alarm_type='zone_enter',
            alarm_level=level,
            worker_id=worker_id,
            worker_name=worker_name,
            worker_x=x,
            worker_y=y,
            geofence=fence,
            message=msg,
        )
        alarms.append({
            'alarm_id': alarm.id,
            'alarm_type': 'zone_enter',
            'alarm_level': level,
            'worker_id': worker_id,
            'worker_name': worker_name,
            'geofence_id': fence.id,
            'geofence_name': fence.name,
            'message': msg,
        })

    # 이탈
    if exited_ids:
        for fence in GeoFence.objects.filter(id__in=exited_ids, zone_type__in=_ALERT_ZONE_TYPES):
            msg = f"{worker_name} [{fence.name}] 이탈"
            alarm = Alarm.objects.create(
                alarm_type='zone_exit',
                alarm_level='info',
                worker_id=worker_id,
                worker_name=worker_name,
                worker_x=x,
                worker_y=y,
                geofence=fence,
                message=msg,
            )
            alarms.append({
                'alarm_id': alarm.id,
                'alarm_type': 'zone_exit',
                'alarm_level': 'info',
                'worker_id': worker_id,
                'worker_name': worker_name,
                'geofence_id': fence.id,
                'geofence_name': fence.name,
                'message': msg,
            })

    return alarms


# ═══════════════════════════════════════════════════════════
# 센서 축 — 장비 1개의 알람 판정
# ═══════════════════════════════════════════════════════════

def evaluate_sensor(device_id: str, sensor_type: str,
                     observed_status: str, detail: str = '') -> list[dict]:
    """
    센서 1개의 상태 전이 판정 + 필요 시 알람 생성.

    [Gas 병합] 알람 생성 시 _find_sensor_geofence 로 소속 geofence 자동 연결.
    """
    if observed_status not in ("normal", "caution", "danger"):
        return []

    snap = get_sensor_snapshot(device_id)
    official_state = snap['state']
    last_alarm_at = snap['last_alarm_at']

    now = time.time()

    # ─── 전이 확정 여부 ───
    confirmed_new_state = None

    if observed_status == official_state:
        if snap['pending_state']:
            clear_sensor_pending(device_id)
    elif _is_sensor_escalation(official_state, observed_status):
        confirmed_new_state = observed_status
    else:
        if snap['pending_state'] == observed_status:
            new_count = snap['pending_count'] + 1
            if new_count >= RECOVERY_CONFIRM_TICKS:
                confirmed_new_state = observed_status
            else:
                set_sensor_pending(device_id, observed_status, new_count)
        else:
            set_sensor_pending(device_id, observed_status, 1)

    # ─── 알람 발행 여부 ───
    should_alarm = False
    reason = None
    target_state = official_state

    if confirmed_new_state is not None:
        should_alarm = True
        reason = 'transition'
        target_state = confirmed_new_state
    elif official_state != 'normal' and (now - last_alarm_at) >= RE_ALARM_INTERVAL_SEC:
        should_alarm = True
        reason = 'ongoing'
        target_state = official_state

    # ─── 알람 생성 ───
    created = []

    if should_alarm:
        alarm_type, alarm_level = _sensor_transition_to_type_and_level(
            official_state, target_state
        )
        message = _build_sensor_message(
            device_id, sensor_type, official_state, target_state, detail
        )

        # 센서 소속 geofence — normal 복귀 외에는 연결
        fence = _find_sensor_geofence(device_id) if target_state != 'normal' else None

        alarm = Alarm.objects.create(
            alarm_type=alarm_type,
            alarm_level=alarm_level,
            device_id=device_id,
            sensor_type=sensor_type,
            geofence=fence,
            message=message,
        )

        created.append({
            'alarm_id': alarm.id,
            'alarm_type': alarm_type,
            'alarm_level': alarm_level,
            'device_id': device_id,
            'sensor_type': sensor_type,
            'geofence_id':   fence.id if fence else None,
            'geofence_name': fence.name if fence else '',
            'message': message,
            'reason': reason,
            'state_from': official_state,
            'state_to': target_state,
        })

        if confirmed_new_state is not None:
            commit_sensor_state(device_id, target_state, mark_alarmed=True)
        else:
            commit_sensor_state(device_id, official_state, mark_alarmed=True)

    return created


def _is_sensor_escalation(prev: str, curr: str) -> bool:
    """센서 상태 악화 여부. normal < caution < danger"""
    ladder = {'normal': 0, 'caution': 1, 'danger': 2}
    return ladder.get(curr, 0) > ladder.get(prev, 0)


def _sensor_transition_to_type_and_level(prev: str, curr: str) -> tuple[str, str]:
    """센서 전이 → (alarm_type, alarm_level)."""
    if prev == 'normal' and curr == 'caution':
        return 'sensor_caution', 'caution'
    if prev == 'normal' and curr == 'danger':
        return 'sensor_danger', 'danger'
    if prev == 'caution' and curr == 'danger':
        return 'sensor_danger', 'danger'
    if prev == 'danger' and curr == 'caution':
        return 'sensor_recover_partial', 'info'
    if prev in ('danger', 'caution') and curr == 'normal':
        return 'sensor_recover_normal', 'info'
    # 지속
    if curr == 'danger':
        return 'sensor_danger', 'danger'
    if curr == 'caution':
        return 'sensor_caution', 'caution'
    return 'sensor_recover_normal', 'info'


def _build_sensor_message(device_id: str, sensor_type: str,
                          prev: str, curr: str, detail: str) -> str:
    """센서 전이별 메시지 (간결형)."""
    label_map = {'gas': '가스센서', 'power': '전력센서'}
    label = label_map.get(sensor_type, '센서')
    detail_str = f" [{detail}]" if detail else ''

    if prev == 'normal' and curr == 'caution':
        return f"{label} {device_id} 주의 수준 감지{detail_str}"
    if prev == 'normal' and curr == 'danger':
        return f"{label} {device_id} 위험 수준 감지{detail_str}"
    if prev == 'caution' and curr == 'danger':
        return f"{label} {device_id} 상태 악화 — 주의→위험{detail_str}"
    if prev == 'danger' and curr == 'caution':
        return f"{label} {device_id} 위험 벗어남 — 주의 수준으로 회복"
    if prev in ('danger', 'caution') and curr == 'normal':
        return f"{label} {device_id} 정상 복귀 — {prev} 상황 종료"
    if curr == 'danger':
        return f"{label} {device_id} 위험 상황 지속 중{detail_str}"
    if curr == 'caution':
        return f"{label} {device_id} 주의 상황 지속 중{detail_str}"

    return f"{label} {device_id} 상태 변화"
