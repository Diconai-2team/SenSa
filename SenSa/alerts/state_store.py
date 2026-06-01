"""
alerts/state_store.py — 작업자별 알람 상태 + 안정화 카운터 (Redis)

저장 구조 (Hash):
  sensa:worker:{worker_id}:alarm
    state           : "safe" | "caution" | "danger"   (현재 공식 상태)
    last_alarm_at   : "1745380923.456"                  (마지막 알람 발행 시각)
    pending_state   : "safe" | "caution" | "danger"    (회복 후보 상태, 아직 미확정)
    pending_count   : "2"                                (후보 상태 연속 관측 횟수)

TTL: 5분.

[9차 ㅁ-fix 변경]
  redis.ConnectionError 가 caller(evaluate_worker → DRF view) 까지 전파되어
  HTTP 500 폭주 + SensorData 트랜잭션 롤백 + 측정값 영구 손실되는 결함 차단.
  _graceful_redis 데코레이터로 read 8 + write 6 함수 일괄 graceful 처리.

  - read 함수 (get_*_snapshot): 기본 dict 반환 (state='safe'/'normal' default)
                                 → caller 가 "no alarm history" 로 자연 처리
  - write 함수 (commit_*, set_*, clear_*): None 반환 (silent skip)
                                            → Redis 복구 후 다음 호출에서 정상 동작

  설계 원칙:
    redis.ConnectionError 만 catch — 그 외 예외(ValueError 등)는 그대로 전파
    (silent failure 방지). logger.warning 으로 명시적 기록.
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
TTL_SEC = 300


@_graceful_redis(default_factory=_worker_default)
def get_worker_snapshot(worker_id: str) -> dict:
    """
    작업자의 현재 전체 스냅샷 반환.
    기본값:
      state='safe', last_alarm_at=0.0, pending_state=None, pending_count=0
    """
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    data = r.hgetall(key)
    return {
        'state': data.get('state', 'safe'),
        'last_alarm_at': float(data.get('last_alarm_at', 0) or 0),
        'pending_state': data.get('pending_state') or None,
        'pending_count': int(data.get('pending_count', 0) or 0),
    }


@_graceful_redis()
def commit_state(worker_id: str, state: str, mark_alarmed: bool = False) -> None:
    """
    공식 상태 확정 + pending 초기화.
    mark_alarmed=True 면 last_alarm_at 도 now 로 갱신.
    """
    if state not in ("safe", "caution", "danger", "critical"):
        raise ValueError(f"invalid state: {state}")
    
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    mapping = {
        'state': state,
        'pending_state': '',
        'pending_count': '0',
    }
    if mark_alarmed:
        mapping['last_alarm_at'] = str(time.time())
    r.hset(key, mapping=mapping)
    r.expire(key, TTL_SEC)


@_graceful_redis()
def set_pending(worker_id: str, pending_state: str, count: int) -> None:
    """
    회복 후보 상태 저장 (아직 확정 안 함).
    상태 자체(state 필드)는 건드리지 않음.
    """
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    r.hset(key, mapping={
        'pending_state': pending_state,
        'pending_count': str(count),
    })
    r.expire(key, TTL_SEC)


@_graceful_redis()
def clear_pending(worker_id: str) -> None:
    """회복 후보 폐기 (현재 상태를 유지함을 의미)."""
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    r.hset(key, mapping={
        'pending_state': '',
        'pending_count': '0',
    })
    r.expire(key, TTL_SEC)

# ═══════════════════════════════════════════════════════════
# 센서용 상태 저장소 (구조는 작업자와 동일)
# ═══════════════════════════════════════════════════════════

SENSOR_KEY_FORMAT = "sensa:sensor:{device_id}:alarm"


@_graceful_redis(default_factory=_sensor_default)
def get_sensor_snapshot(device_id: str) -> dict:
    """센서의 현재 스냅샷.

    v2 추가: pending_{caution,danger,normal}_count + _first_at 6개 필드.
    각 status별 독립 윈도우 카운터.
    """
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    data = r.hgetall(key)
    return {
        'state': data.get('state', 'normal'),
        'last_alarm_at': float(data.get('last_alarm_at', 0) or 0),
        'pending_state': data.get('pending_state') or None,
        'pending_count': int(data.get('pending_count', 0) or 0),
        # v2: 윈도우 누적 카운터 (status별 독립)
        'pending_caution_count':    int(data.get('pending_caution_count', 0) or 0),
        'pending_caution_first_at': float(data.get('pending_caution_first_at', 0) or 0),
        'pending_danger_count':     int(data.get('pending_danger_count', 0) or 0),
        'pending_danger_first_at':  float(data.get('pending_danger_first_at', 0) or 0),
        'pending_normal_count':     int(data.get('pending_normal_count', 0) or 0),
        'pending_normal_first_at':  float(data.get('pending_normal_first_at', 0) or 0),
    }


@_graceful_redis()
def set_sensor_window_counter(device_id: str, status: str,
                                count: int, first_at: float) -> None:
    """observed_status별 윈도우 카운터 + 첫 신호 시각 저장 (v2)."""
    if status not in ('normal', 'caution', 'danger'):
        raise ValueError(f"invalid status: {status}")
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(key, mapping={
        f'pending_{status}_count': str(count),
        f'pending_{status}_first_at': str(first_at),
    })
    r.expire(key, TTL_SEC)


@_graceful_redis()
def clear_sensor_window_counters(device_id: str) -> None:
    """v2: confirm 직후 모든 windowed 카운터 리셋."""
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(key, mapping={
        'pending_caution_count':    '0', 'pending_caution_first_at': '0',
        'pending_danger_count':     '0', 'pending_danger_first_at':  '0',
        'pending_normal_count':     '0', 'pending_normal_first_at':  '0',
    })
    r.expire(key, TTL_SEC)


@_graceful_redis()
def commit_sensor_state(device_id: str, state: str, mark_alarmed: bool = False) -> None:
    """센서 공식 상태 확정."""
    if state not in ("normal", "caution", "danger"):
        raise ValueError(f"invalid sensor state: {state}")
    
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    mapping = {
        'state': state,
        'pending_state': '',
        'pending_count': '0',
    }
    if mark_alarmed:
        mapping['last_alarm_at'] = str(time.time())
    r.hset(key, mapping=mapping)
    r.expire(key, TTL_SEC)


@_graceful_redis()
def set_sensor_pending(device_id: str, pending_state: str, count: int) -> None:
    """센서 회복 후보 저장."""
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(key, mapping={
        'pending_state': pending_state,
        'pending_count': str(count),
    })
    r.expire(key, TTL_SEC)


@_graceful_redis()
def clear_sensor_pending(device_id: str) -> None:
    """센서 회복 후보 폐기."""
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(key, mapping={
        'pending_state': '',
        'pending_count': '0',
    })
    r.expire(key, TTL_SEC)
