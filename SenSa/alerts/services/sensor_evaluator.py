"""
alerts/services/sensor_evaluator.py — 장비 1개의 알람 판정 (메인 진입점).

Public API: evaluate_sensor(device_id, sensor_type, observed_status, detail='')
사용처: dashboard/views.py 의 sensor data 처리 핸들러.
"""
import time
from .anomaly_detector import detect_anomaly
from ..models import Alarm
from ..state_store import (
    get_sensor_snapshot, commit_sensor_state,
    set_sensor_pending, clear_sensor_pending,
    # v2: 윈도우 카운터
    set_sensor_window_counter, clear_sensor_window_counters,
)
# v3: 알람 실시간 WebSocket push
from realtime.publishers import publish_alarm
import logging
logger = logging.getLogger(__name__)

# v3: 상태 순위 (V자 진동 차단용)
_STATE_RANK = {'normal': 0, 'caution': 1, 'danger': 2}
from ._common import (
    RE_ALARM_INTERVAL_SEC,
    RECOVERY_CONFIRM_TICKS,        # v1 잔존 (worker_evaluator 호환)
    CAUTION_CONFIRM_TICKS,         # v1 잔존 (legacy)
    # v2 윈도우 누적 상수
    CAUTION_WINDOW_SEC, CAUTION_COUNT_THRESHOLD, DANGER_COUNT_THRESHOLD,
    RECOVERY_WINDOW_SEC, RECOVERY_COUNT_THRESHOLD,
)
from .geofence_utils import _find_sensor_geofence
# [P4-C 8차] 알람 비즈니스 메트릭
from alerts.metrics import alarm_created_total, alarm_throttled_total


def evaluate_sensor(device_id: str, sensor_type: str,
                     observed_status: str, detail: str = '',
                     raw_value: float | None = None,
                     is_ai: bool = False,
                     ai_detail: str = '') -> list[dict]:
    """
    센서 1개의 상태 전이 판정 + 필요 시 알람 생성.

    Args:
        is_ai     : ARIMA 탐지로 격상된 경우 True
        ai_detail : 이상 탐지된 센서 종류 문자열 (예: "CO, H2S")
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
        # v3: V자 진동 차단 — 격하 방향 카운터들 리셋
        # observed==official 신호가 들어오면 "상태 유지" 의미.
        # 격하 카운터(official보다 안전한 상태)를 0으로 리셋해서
        # 반대 source(예: generator normal)가 누적시킨 false 격하 진행을 차단.
        # 격상 카운터는 그대로 — 진짜 격상 진행은 보호.
        official_rank = _STATE_RANK.get(official_state, 0)
        for st in ('normal', 'caution', 'danger'):
            if _STATE_RANK[st] < official_rank:
                set_sensor_window_counter(device_id, st, 0, 0)
    elif _is_sensor_escalation(official_state, observed_status):
        # v2 격상: observed_status별 독립 윈도우 카운터 누적
        # V자 진동(Celery danger + generator normal 동시) 환경에서도 정확
        threshold = (DANGER_COUNT_THRESHOLD if observed_status == 'danger'
                     else CAUTION_COUNT_THRESHOLD)
        confirmed_new_state = _accumulate_window(
            snap, observed_status, now, CAUTION_WINDOW_SEC, threshold, device_id,
        )
    else:
        # v2 격하 (recovery): 더 보수적 임계 (윈도우 안 7회)
        confirmed_new_state = _accumulate_window(
            snap, observed_status, now,
            RECOVERY_WINDOW_SEC, RECOVERY_COUNT_THRESHOLD, device_id,
        )

    # v2: confirmed 시 모든 윈도우 카운터 리셋
    if confirmed_new_state is not None:
        clear_sensor_window_counters(device_id)

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

    # [P4-C 8차] throttle 차단 카운트
    #   조건: 이상 상태(non-normal) 인데 should_alarm=False → 60s 안에 재발 시도였음
    if (not should_alarm) and official_state != 'normal' and confirmed_new_state is None:
        try:
            alarm_throttled_total.labels(
                sensor_type=sensor_type,
                reason='within_interval',
            ).inc()
        except Exception:
            pass  # 메트릭 실패가 알람 로직을 끊지 않도록 격리

    # ─── 알람 생성 ───
    created = []

    if should_alarm:
        alarm_type, alarm_level = _sensor_transition_to_type_and_level(
            official_state, target_state
        )
        message = _build_sensor_message(
            device_id, sensor_type, official_state, target_state,
            detail, is_ai, ai_detail
        )

        fence = _find_sensor_geofence(device_id) if target_state != 'normal' else None

        alarm = Alarm.objects.create(
            alarm_type=alarm_type,
            alarm_level=alarm_level,
            device_id=device_id,
            sensor_type=sensor_type,
            geofence=fence,
            message=message,
            is_ai=is_ai,
        )

        # [P4-C 8차] 알람 생성 메트릭 — alarm_level/reason 별 누적
        try:
            alarm_created_total.labels(
                sensor_type=sensor_type,
                alarm_level=alarm_level,
                reason=reason or 'unknown',
            ).inc()
        except Exception:
            pass

        alarm_payload = {
            'alarm_id':      alarm.id,
            'alarm_type':    alarm_type,
            'alarm_level':   alarm_level,
            'device_id':     device_id,
            'sensor_type':   sensor_type,
            'geofence_id':   fence.id if fence else None,
            'geofence_name': fence.name if fence else '',
            'message':       message,
            'reason':        reason,
            'state_from':    official_state,
            'state_to':      target_state,
            'is_ai':         is_ai,
            'created_at':    alarm.created_at.isoformat(),
        }
        created.append(alarm_payload)

        # v3: WebSocket 실시간 push (frontend 알람 패널 + 좌측 토스트 즉시 갱신)
        # devices/views.py 경로의 publish_alarm과 동일 페이로드.
        # 시나리오 sustain_spike_task가 직접 evaluate_sensor 호출하는 경로에서
        # 이전엔 DB 저장만 하고 push 누락 → frontend 새로고침해야만 보였음.
        try:
            publish_alarm(alarm_payload)
        except Exception as e:
            logger.warning('[evaluate_sensor] publish_alarm 실패: %s', e)

        if confirmed_new_state is not None:
            commit_sensor_state(device_id, target_state, mark_alarmed=True)
        else:
            commit_sensor_state(device_id, official_state, mark_alarmed=True)

    return created


def _accumulate_window(snap: dict, observed: str, now: float,
                        window_sec: float, threshold: int,
                        device_id: str):
    """v2: observed_status별 독립 카운터 누적.

    윈도우(window_sec) 안에 같은 observed 신호가 threshold회 들어오면 confirm.
    다른 신호가 끼어도 해당 카운터는 영향 받지 않음 (독립).

    Returns:
        confirmed_new_state: 임계 도달 시 observed, 아니면 None
    """
    cnt = snap.get(f'pending_{observed}_count', 0)
    first_at = snap.get(f'pending_{observed}_first_at', 0.0)

    # 윈도우 만료 또는 첫 누적 → 새로 시작
    if first_at == 0 or (now - first_at) > window_sec:
        new_count, new_first = 1, now
    else:
        new_count, new_first = cnt + 1, first_at

    if new_count >= threshold:
        # 임계 도달 — confirmed 반환 (호출 측에서 모든 카운터 clear)
        return observed
    set_sensor_window_counter(device_id, observed, new_count, new_first)
    return None


def _is_sensor_escalation(prev: str, curr: str) -> bool:
    ladder = {'normal': 0, 'caution': 1, 'danger': 2}
    return ladder.get(curr, 0) > ladder.get(prev, 0)


def _sensor_transition_to_type_and_level(prev: str, curr: str) -> tuple[str, str]:
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
    if curr == 'danger':
        return 'sensor_danger', 'danger'
    if curr == 'caution':
        return 'sensor_caution', 'caution'
    return 'sensor_recover_normal', 'info'


def _build_sensor_message(device_id: str, sensor_type: str,
                          prev: str, curr: str, detail: str,
                          is_ai: bool = False,
                          ai_detail: str = '') -> str:
    """
    센서 전이별 메시지.

    is_ai=True 시:
      "AI예측 - sensor_01 CO, H2S 이상!"
      "AI예측 - power_01 전력 이상!"
    is_ai=False 시: 기존 메시지 유지.
    """
    label_map = {'gas': '가스센서', 'power': '전력센서'}
    label = label_map.get(sensor_type, '센서')
    detail_str = f" [{detail}]" if detail else ''

    # ─── ARIMA AI 탐지 메시지 ───
    if is_ai and ai_detail:
        if curr == 'caution':
            return f"AI예측 - {device_id} {ai_detail} 이상!"
        if curr == 'danger':
            return f"AI예측 - {device_id} {ai_detail} 위험 수준 이상!"
        if curr == 'normal':
            return f"AI예측 - {device_id} {ai_detail} 정상 복귀"

    # ─── 기존 고정 임계치 메시지 ───
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
