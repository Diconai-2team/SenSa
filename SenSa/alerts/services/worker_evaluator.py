"""
alerts/services/worker_evaluator.py — 작업자 1명의 알람 판정 (메인 진입점).

Public API: evaluate_worker(worker_id, worker_name, x, y, ...)
사용처: dashboard/views.py 의 worker location 처리 핸들러.

내부 헬퍼 (이 모듈 안에서만 사용):
  _classify_state              — 좌표·센서 → 상태 ('safe'/'caution'/'danger'/'critical')
  _pick_primary_geofence       — 알람 메시지용 대표 지오펜스 선택
  _build_message               — 전이별 메시지 조립 (B3 인자: influencing_sensors)
  _transition_to_type_and_level — 전이 → (alarm_type, alarm_level) 매핑
  _is_escalation               — 악화 여부 (safe < caution < danger < critical)

상태 정의:
  'safe' < 'caution' < 'danger' < 'critical'
  critical = restricted(출입금지) 구역 안 (Gas 병합)

Hysteresis 정책:
  - 악화 (escalation): 즉시 전이
  - 회복 (recovery)  : RECOVERY_CONFIRM_TICKS 회 연속 관측 후 전이
"""
import time

from ..models import Alarm
from ..state_store import (
    get_worker_snapshot, commit_state, set_pending, clear_pending,
)
from ._common import RE_ALARM_INTERVAL_SEC, RECOVERY_CONFIRM_TICKS
from .geofence_utils import _find_containing_geofences


# ═══════════════════════════════════════════════════════════
# 상태 분류 / 메시지 / 전이 매핑
# ═══════════════════════════════════════════════════════════

def _classify_state(geofences: list, worst_sensor_status: str) -> str:
    """
    현재 상태 판정.
    반환: 'safe' | 'caution' | 'danger' | 'critical'

    critical 승격 조건: 작업자가 restricted(출입금지) 구역 안에 있을 때.
    """
    zone_types = {g.zone_type for g in geofences}

    if 'restricted' in zone_types:
        return 'critical'

    if 'danger' in zone_types or worst_sensor_status == 'danger':
        return 'danger'

    if 'caution' in zone_types or worst_sensor_status == 'caution':
        return 'caution'

    return 'safe'


def _pick_primary_geofence(geofences: list, target_state: str):
    """알람 메시지에 표시할 '대표' 지오펜스 선택."""
    for g in geofences:
        zone_type = g.zone_type
        if target_state == 'critical' and zone_type == 'restricted':
            return g
        if target_state == 'danger' and zone_type in ('danger', 'restricted'):
            return g
        if target_state == 'caution' and zone_type == 'caution':
            return g
    return geofences[0] if geofences else None


def _build_message(worker_name: str, prev: str, curr: str,
                    geofence, sensor_status: str,
                    influencing_sensors: list | None = None) -> str:
    """
    전이별 메시지 조립.

    [팀원 병합 v1 — B3]
      influencing_sensors 인자 추가. 알람 원인 센서가 있으면
      지오펜스 이름 대신 "(sensor_01 danger, sensor_03 caution)" 형태로 표기.
      근거: 산업안전 ISO 45001 — 사고 조사 시 근본 원인 추적성 강화.

      우선순위: zone_name (지오펜스) > 영향 센서 ID > 기본 "(센서 주의)"
      → 지오펜스 기반 알람은 기존 포맷 그대로, 센서 기반 알람만 구체화됨.
    """
    zone_name = geofence.name if geofence else ''
    influencing_sensors = influencing_sensors or []

    # ─── 센서 상세 suffix 빌더 (B3) ───
    # 지오펜스명이 있으면 그것을 우선. 없고 영향 센서가 있으면 센서 ID 노출.
    def _sensor_suffix(default_suffix: str) -> str:
        """
        zone_name 이 있으면 " (zone_name)", 없고 센서가 있으면 " (sensor_XX status, ...)",
        둘 다 없으면 default_suffix (예: " (센서 주의)") 반환.
        """
        if zone_name:
            return f" ({zone_name})"
        if influencing_sensors:
            # 같은 상태 여러 개: "(sensor_01, sensor_03 caution)"
            # 상태 섞임:        "(sensor_01 danger, sensor_03 caution)"
            statuses = {st for _, st in influencing_sensors}
            if len(statuses) == 1:
                only_status = next(iter(statuses))
                ids = ', '.join(sid for sid, _ in influencing_sensors)
                return f" ({ids} {only_status})"
            parts = [f"{sid} {st}" for sid, st in influencing_sensors]
            return f" ({', '.join(parts)})"
        return default_suffix

    # ─── critical (restricted 구역) ───
    if curr == 'critical' and prev != 'critical':
        return f"{worker_name} 출입금지구역 진입" + (f" ({zone_name})" if zone_name else "")
    if prev == 'critical' and curr == 'critical':
        return f"{worker_name} 출입금지구역 체류 중" + (f" ({zone_name})" if zone_name else "")
    if prev == 'critical' and curr == 'danger':
        return f"{worker_name} 출입금지구역 이탈 — 위험 수준으로 낮아짐"
    if prev == 'critical' and curr in ('caution', 'safe'):
        return f"{worker_name} 출입금지구역 이탈 완료"

    # ─── 악화 ───
    if prev == 'safe' and curr == 'caution':
        return f"{worker_name} 주의구역 진입" + _sensor_suffix(" (센서 주의)")
    if prev == 'safe' and curr == 'danger':
        return f"{worker_name} 위험구역 진입" + _sensor_suffix(" (센서 위험)")
    if prev == 'caution' and curr == 'danger':
        return f"{worker_name} 상태 악화 — 주의→위험" + _sensor_suffix("")

    # ─── 회복 ───
    if prev == 'danger' and curr == 'caution':
        return f"{worker_name} 위험 벗어남 — 주의 수준으로 회복"
    if prev == 'danger' and curr == 'safe':
        return f"{worker_name} 안전지역 복귀 — 위험 상황 종료"
    if prev == 'caution' and curr == 'safe':
        return f"{worker_name} 안전지역 복귀 — 주의 상황 종료"

    # ─── 지속 ───
    if curr == 'danger':
        return f"{worker_name} 위험 상황 지속 중" + _sensor_suffix("")
    if curr == 'caution':
        return f"{worker_name} 주의 상황 지속 중" + _sensor_suffix("")

    return f"{worker_name} 상태 변화"


def _transition_to_type_and_level(prev: str, curr: str) -> tuple[str, str]:
    """전이 유형 → (alarm_type, alarm_level) 매핑."""
    # critical 진입
    if curr == 'critical' and prev != 'critical':
        return 'state_danger_enter', 'critical'
    # critical 에서 회복
    if prev == 'critical' and curr == 'danger':
        return 'state_recover_partial', 'info'
    if prev == 'critical' and curr in ('caution', 'safe'):
        return 'state_recover_safe', 'info'
    if prev == 'critical' and curr == 'critical':
        return 'state_ongoing', 'critical'

    # 기존 전이
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
    # 지속
    if curr == 'danger':
        return 'state_ongoing', 'danger'
    if curr == 'caution':
        return 'state_ongoing', 'caution'
    return 'state_ongoing', 'info'


def _is_escalation(prev: str, curr: str) -> bool:
    """상태 악화 여부. safe < caution < danger < critical"""
    ladder = {'safe': 0, 'caution': 1, 'danger': 2, 'critical': 3}
    return ladder.get(curr, 0) > ladder.get(prev, 0)


# ═══════════════════════════════════════════════════════════
# 메인 진입점
# ═══════════════════════════════════════════════════════════

def evaluate_worker(worker_id: str, worker_name: str,
                     x: float, y: float,
                     worst_sensor_status: str = 'normal',
                     influencing_sensors: list | None = None) -> list[dict]:
    """
    작업자 1명의 상태 전이 판정 + 필요 시 알람 생성.

    Hysteresis:
      - 악화: 즉시 전이
      - 회복: N틱(기본 3) 연속 관측 후 전이 (노이즈 필터)

    [팀원 병합 v1 — B3]
      influencing_sensors: [(device_id, status), ...] — 작업자 근접 반경 내
        비정상 센서 목록. _build_message 로 전달되어 알람 메시지에 반영됨.
        기본값 None 이면 기존 동작과 동일 (하위 호환).
    """
    geofences = _find_containing_geofences(x, y)
    observed_state = _classify_state(geofences, worst_sensor_status)
    snap = get_worker_snapshot(worker_id)
    official_state = snap['state']
    last_alarm_at = snap['last_alarm_at']

    now = time.time()

    # 디버그 로그
    since_last = now - last_alarm_at if last_alarm_at > 0 else -1
    print(f"[DEBUG] {worker_id} ({x:.1f},{y:.1f}) "
          f"official={official_state} observed={observed_state} "
          f"pending={snap['pending_state']}({snap['pending_count']}) "
          f"since_last={since_last:.1f}s "
          f"fences={[g.name for g in geofences]} "
          f"sensor={worst_sensor_status}")

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

    # ─── 알람 발행 여부 ───
    should_alarm = False
    reason = None
    target_state = official_state

    if confirmed_new_state is not None:
        should_alarm = True
        reason = 'transition'
        target_state = confirmed_new_state
    elif official_state != 'safe' and (now - last_alarm_at) >= RE_ALARM_INTERVAL_SEC:
        should_alarm = True
        reason = 'ongoing'
        target_state = official_state

    # ─── 알람 생성 + 상태 커밋 ───
    created = []

    if should_alarm:
        alarm_type, alarm_level = _transition_to_type_and_level(official_state, target_state)
        primary_fence = _pick_primary_geofence(geofences, target_state)
        message = _build_message(
            worker_name, official_state, target_state,
            primary_fence, worst_sensor_status,
            influencing_sensors=influencing_sensors,   # B3: 영향 센서 목록 전달
        )

        alarm = Alarm.objects.create(
            alarm_type=alarm_type,
            alarm_level=alarm_level,
            worker_id=worker_id,
            worker_name=worker_name,
            worker_x=x,
            worker_y=y,
            geofence=primary_fence if target_state != 'safe' else None,
            message=message,
        )

        created.append({
            'alarm_id': alarm.id,
            'alarm_type': alarm_type,
            'alarm_level': alarm_level,
            'worker_id': worker_id,
            'worker_name': worker_name,
            'geofence_id': primary_fence.id if primary_fence and target_state != 'safe' else None,
            'geofence_name': primary_fence.name if primary_fence and target_state != 'safe' else '',
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

    return created
