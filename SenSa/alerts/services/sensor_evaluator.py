"""
alerts/services/sensor_evaluator.py — 장비 1개의 알람 판정 (메인 진입점).

Public API: evaluate_sensor(device_id, sensor_type, observed_status, detail='')
사용처: dashboard/views.py 의 sensor data 처리 핸들러.

내부 헬퍼:
  _is_sensor_escalation              — 악화 여부 (normal < caution < danger)
  _sensor_transition_to_type_and_level — 전이 → (alarm_type, alarm_level)
  _build_sensor_message              — 전이별 메시지 (간결형)

worker_evaluator 와 별개의 axis. 둘 다 state_store 만 공유, 함수 호출은 안 함.
"""
import time

from ..models import Alarm
from ..state_store import (
    get_sensor_snapshot, commit_sensor_state,
    set_sensor_pending, clear_sensor_pending,
)
from ._common import RE_ALARM_INTERVAL_SEC, RECOVERY_CONFIRM_TICKS
from .geofence_utils import _find_sensor_geofence


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
