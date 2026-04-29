"""
alerts/state_store.py — 작업자별 알람 상태 + 안정화 카운터 (Redis)

저장 구조 (Hash):
  sensa:worker:{worker_id}:alarm
    state           : "safe" | "caution" | "danger"   (현재 공식 상태)
    last_alarm_at   : "1745380923.456"                  (마지막 알람 발행 시각)
    pending_state   : "safe" | "caution" | "danger"    (회복 후보 상태, 아직 미확정)
    pending_count   : "2"                                (후보 상태 연속 관측 횟수)

TTL: 5분.
"""

import time
import redis
from django.conf import settings


_pool = None


def _client() -> redis.Redis:
    """Channels 설정의 Redis 호스트를 재사용."""
    global _pool
    if _pool is None:
        host_tuple = settings.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"][0]
        if isinstance(host_tuple, (tuple, list)):
            host, port = host_tuple
            _pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
        else:
            _pool = redis.ConnectionPool.from_url(host_tuple, decode_responses=True)
    return redis.Redis(connection_pool=_pool)


KEY_FORMAT = "sensa:worker:{worker_id}:alarm"
TTL_SEC = 300


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
        "state": data.get("state", "safe"),
        "last_alarm_at": float(data.get("last_alarm_at", 0) or 0),
        "pending_state": data.get("pending_state") or None,
        "pending_count": int(data.get("pending_count", 0) or 0),
    }


def commit_state(worker_id: str, state: str, mark_alarmed: bool = False) -> None:
    """
    공식 상태 확정 + pending 초기화.
    mark_alarmed=True 면 last_alarm_at 도 now 로 갱신.
    """
    if state not in ("safe", "caution", "danger"):
        raise ValueError(f"invalid state: {state}")

    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    mapping = {
        "state": state,
        "pending_state": "",
        "pending_count": "0",
    }
    if mark_alarmed:
        mapping["last_alarm_at"] = str(time.time())
    r.hset(key, mapping=mapping)
    r.expire(key, TTL_SEC)


def set_pending(worker_id: str, pending_state: str, count: int) -> None:
    """
    회복 후보 상태 저장 (아직 확정 안 함).
    상태 자체(state 필드)는 건드리지 않음.
    """
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    r.hset(
        key,
        mapping={
            "pending_state": pending_state,
            "pending_count": str(count),
        },
    )
    r.expire(key, TTL_SEC)


def clear_pending(worker_id: str) -> None:
    """회복 후보 폐기 (현재 상태를 유지함을 의미)."""
    r = _client()
    key = KEY_FORMAT.format(worker_id=worker_id)
    r.hset(
        key,
        mapping={
            "pending_state": "",
            "pending_count": "0",
        },
    )
    r.expire(key, TTL_SEC)


# ═══════════════════════════════════════════════════════════
# 센서용 상태 저장소 (구조는 작업자와 동일)
# ═══════════════════════════════════════════════════════════

SENSOR_KEY_FORMAT = "sensa:sensor:{device_id}:alarm"


def get_sensor_snapshot(device_id: str) -> dict:
    """센서의 현재 스냅샷."""
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    data = r.hgetall(key)
    return {
        "state": data.get("state", "normal"),
        "last_alarm_at": float(data.get("last_alarm_at", 0) or 0),
        "pending_state": data.get("pending_state") or None,
        "pending_count": int(data.get("pending_count", 0) or 0),
    }


def commit_sensor_state(device_id: str, state: str, mark_alarmed: bool = False) -> None:
    """센서 공식 상태 확정."""
    if state not in ("normal", "caution", "danger"):
        raise ValueError(f"invalid sensor state: {state}")

    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    mapping = {
        "state": state,
        "pending_state": "",
        "pending_count": "0",
    }
    if mark_alarmed:
        mapping["last_alarm_at"] = str(time.time())
    r.hset(key, mapping=mapping)
    r.expire(key, TTL_SEC)


def set_sensor_pending(device_id: str, pending_state: str, count: int) -> None:
    """센서 회복 후보 저장."""
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(
        key,
        mapping={
            "pending_state": pending_state,
            "pending_count": str(count),
        },
    )
    r.expire(key, TTL_SEC)


def clear_sensor_pending(device_id: str) -> None:
    """센서 회복 후보 폐기."""
    r = _client()
    key = SENSOR_KEY_FORMAT.format(device_id=device_id)
    r.hset(
        key,
        mapping={
            "pending_state": "",
            "pending_count": "0",
        },
    )
    r.expire(key, TTL_SEC)
