"""
alerts/state_store.py — 작업자별 알람 상태 + 안정화 카운터 (Redis)

저장 구조 (Hash):
  sensa:worker:{worker_id}:alarm
    state           : "safe" | "caution" | "danger"   (현재 공식 상태)
    last_alarm_at   : "1745380923.456"                  (마지막 알람 발행 시각)
    pending_state   : "safe" | "caution" | "danger"    (회복 후보 상태, 아직 미확정)
    pending_count   : "2"                                (후보 상태 연속 관측 횟수)

TTL: 30분.

[수정] Redis 연결 실패 시 fallback 정책 (_graceful_redis 데코레이터):
  - read 함수(get_*_snapshot): 기본 dict 반환 → 알람 파이프라인 정상 진행
  - write 함수(commit_*, set_*, clear_*): None 반환 (silent skip)
  - 데코레이터는 redis.ConnectionError 만 catch (ValueError 등은 그대로 전파).
    내부 try/except Exception 으로 나머지 예외 추가 처리.
  - TTL 30분: 단기 통신 끊김(연결 불안정, 재시작)에서 상태 보존.
"""
import functools
import logging
import time

import redis
from django.conf import settings

logger = logging.getLogger(__name__)


_pool = None


def _client() -> redis.Redis:
    """Channels 설정의 Redis 호스트를 재사용."""
    global _pool
    if _pool is None:
        host_tuple = settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0]
        if isinstance(host_tuple, (tuple, list)):
            host, port = host_tuple
            _pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
        else:
            _pool = redis.ConnectionPool.from_url(host_tuple, decode_responses=True)
    return redis.Redis(connection_pool=_pool)


# ═══════════════════════════════════════════════════════════
# [9차 ㅁ-fix] graceful degradation 데코레이터
# ═══════════════════════════════════════════════════════════

def _graceful_redis(default_factory=None):
    """
    Redis 장애 시 graceful degradation 데코레이터.

    redis.ConnectionError 만 catch — 그 외 예외는 그대로 전파.
    fallback 반환 + logger.warning 으로 명시 기록 (silent failure 방지).

    Args:
        default_factory: ConnectionError 시 반환할 값을 만드는 callable.
                         None 이면 None 반환 (write 함수 용도).
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except redis.ConnectionError as exc:
                logger.warning(
                    "state_store.%s skipped (redis down): %s",
                    fn.__name__, exc,
                )
                return default_factory() if default_factory else None
        return wrapper
    return decorator


def _worker_default() -> dict:
    """get_worker_snapshot 의 Redis 장애 시 기본값."""
    return {
        'state': 'safe',
        'last_alarm_at': 0.0,
        'pending_state': None,
        'pending_count': 0,
    }


def _sensor_default() -> dict:
    """get_sensor_snapshot 의 Redis 장애 시 기본값."""
    return {
        'state': 'normal',
        'last_alarm_at': 0.0,
        'pending_state': None,
        'pending_count': 0,
    }


# ═══════════════════════════════════════════════════════════

KEY_FORMAT = "sensa:worker:{worker_id}:alarm"
# [수정] 5분 → 30분
# 기존 5분 TTL 은 작업자/센서가 5분간 데이터를 안 보내면 상태가 safe/normal 로 초기화됨.
# 재연결 시 이미 caution/danger 상태임에도 state_caution_enter 알람이 재발행되는 문제.
# 30분으로 연장 → 단기 통신 끊김(연결 불안정, 재시작 등)에서 상태 보존.
TTL_SEC = 1800


@_graceful_redis(default_factory=_worker_default)
def get_worker_snapshot(worker_id: str) -> dict:
    """
    작업자의 현재 전체 스냅샷 반환.
    기본값:
      state='safe', last_alarm_at=0.0, pending_state=None, pending_count=0

    [수정] Redis 연결 실패 시 기본값 반환 — 알람 파이프라인이 중단되지 않도록 fallback.
    """
    try:
        r = _client()
        key = KEY_FORMAT.format(worker_id=worker_id)
        data = r.hgetall(key)
        return {
            'state': data.get('state', 'safe'),
            'last_alarm_at': float(data.get('last_alarm_at', 0) or 0),
            'pending_state': data.get('pending_state') or None,
            'pending_count': int(data.get('pending_count', 0) or 0),
        }
    except Exception as exc:
        logger.warning("[state_store] get_worker_snapshot(%s) Redis 오류 — 기본값 반환: %s", worker_id, exc)
        return {'state': 'safe', 'last_alarm_at': 0.0, 'pending_state': None, 'pending_count': 0}


@_graceful_redis()
def commit_state(worker_id: str, state: str, mark_alarmed: bool = False,
                  preserve_pending: bool = False) -> None:
    """
    공식 상태 확정.
    mark_alarmed=True 면 last_alarm_at 도 now 로 갱신.
    preserve_pending=True 면 pending_state/count 를 건드리지 않음.

    [수정-A] preserve_pending 파라미터 추가.
      ongoing 알람 발행 시 pending 회복 카운터가 리셋되는 버그 수정.
      전이(transition) 시에만 pending 초기화, ongoing 시에는 진행 중인
      회복 카운트를 보존하여 RECOVERY_CONFIRM_TICKS 틱 후 정상 회복 전이.

    [수정-B] Redis 연결 실패 시 경고 로그 후 무시.
    """
    if state not in ("safe", "caution", "danger", "critical"):
        raise ValueError(f"invalid state: {state}")

    try:
        r = _client()
        key = KEY_FORMAT.format(worker_id=worker_id)
        mapping: dict = {'state': state}
        if not preserve_pending:
            mapping['pending_state'] = ''
            mapping['pending_count'] = '0'
        if mark_alarmed:
            mapping['last_alarm_at'] = str(time.time())
        r.hset(key, mapping=mapping)
        r.expire(key, TTL_SEC)
    except Exception as exc:
        logger.warning("[state_store] commit_state(%s, %s) Redis 오류 — 무시: %s", worker_id, state, exc)


@_graceful_redis()
def set_pending(worker_id: str, pending_state: str, count: int) -> None:
    """
    회복 후보 상태 저장 (아직 확정 안 함).
    상태 자체(state 필드)는 건드리지 않음.

    [수정] Redis 연결 실패 시 경고 로그 후 무시.
    """
    try:
        r = _client()
        key = KEY_FORMAT.format(worker_id=worker_id)
        r.hset(key, mapping={
            'pending_state': pending_state,
            'pending_count': str(count),
        })
        r.expire(key, TTL_SEC)
    except Exception as exc:
        logger.warning("[state_store] set_pending(%s) Redis 오류 — 무시: %s", worker_id, exc)


@_graceful_redis()
def clear_pending(worker_id: str) -> None:
    """
    회복 후보 폐기 (현재 상태를 유지함을 의미).

    [수정] Redis 연결 실패 시 경고 로그 후 무시.
    """
    try:
        r = _client()
        key = KEY_FORMAT.format(worker_id=worker_id)
        r.hset(key, mapping={
            'pending_state': '',
            'pending_count': '0',
        })
        r.expire(key, TTL_SEC)
    except Exception as exc:
        logger.warning("[state_store] clear_pending(%s) Redis 오류 — 무시: %s", worker_id, exc)

# ═══════════════════════════════════════════════════════════
# 센서용 상태 저장소 (구조는 작업자와 동일)
# ═══════════════════════════════════════════════════════════

SENSOR_KEY_FORMAT = "sensa:sensor:{device_id}:alarm"


@_graceful_redis(default_factory=_sensor_default)
def get_sensor_snapshot(device_id: str) -> dict:
    """
    센서의 현재 스냅샷.

    [수정] Redis 연결 실패 시 기본값 반환 — 알람 파이프라인이 중단되지 않도록 fallback.
    """
    try:
        r = _client()
        key = SENSOR_KEY_FORMAT.format(device_id=device_id)
        data = r.hgetall(key)
        return {
            'state': data.get('state', 'normal'),
            'last_alarm_at': float(data.get('last_alarm_at', 0) or 0),
            'pending_state': data.get('pending_state') or None,
            'pending_count': int(data.get('pending_count', 0) or 0),
        }
    except Exception as exc:
        logger.warning("[state_store] get_sensor_snapshot(%s) Redis 오류 — 기본값 반환: %s", device_id, exc)
        return {'state': 'normal', 'last_alarm_at': 0.0, 'pending_state': None, 'pending_count': 0}


@_graceful_redis()
def commit_sensor_state(device_id: str, state: str, mark_alarmed: bool = False,
                         preserve_pending: bool = False) -> None:
    """
    센서 공식 상태 확정.
    preserve_pending=True 면 pending_state/count 를 건드리지 않음.

    [수정-A] preserve_pending 파라미터 추가 — commit_state 와 동일한 이유.
    [수정-B] Redis 연결 실패 시 경고 로그 후 무시.
    """
    if state not in ("normal", "caution", "danger"):
        raise ValueError(f"invalid sensor state: {state}")

    try:
        r = _client()
        key = SENSOR_KEY_FORMAT.format(device_id=device_id)
        mapping: dict = {'state': state}
        if not preserve_pending:
            mapping['pending_state'] = ''
            mapping['pending_count'] = '0'
        if mark_alarmed:
            mapping['last_alarm_at'] = str(time.time())
        r.hset(key, mapping=mapping)
        r.expire(key, TTL_SEC)
    except Exception as exc:
        logger.warning("[state_store] commit_sensor_state(%s, %s) Redis 오류 — 무시: %s", device_id, state, exc)


@_graceful_redis()
def set_sensor_pending(device_id: str, pending_state: str, count: int) -> None:
    """
    센서 회복 후보 저장.

    [수정] Redis 연결 실패 시 경고 로그 후 무시.
    """
    try:
        r = _client()
        key = SENSOR_KEY_FORMAT.format(device_id=device_id)
        r.hset(key, mapping={
            'pending_state': pending_state,
            'pending_count': str(count),
        })
        r.expire(key, TTL_SEC)
    except Exception as exc:
        logger.warning("[state_store] set_sensor_pending(%s) Redis 오류 — 무시: %s", device_id, exc)


@_graceful_redis()
def clear_sensor_pending(device_id: str) -> None:
    """
    센서 회복 후보 폐기.

    [수정] Redis 연결 실패 시 경고 로그 후 무시.
    """
    try:
        r = _client()
        key = SENSOR_KEY_FORMAT.format(device_id=device_id)
        r.hset(key, mapping={
            'pending_state': '',
            'pending_count': '0',
        })
        r.expire(key, TTL_SEC)
    except Exception as exc:
        logger.warning("[state_store] clear_sensor_pending(%s) Redis 오류 — 무시: %s", device_id, exc)
