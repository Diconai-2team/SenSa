"""
ml_engine/sliding_window.py — Redis ZSET 기반 슬라이딩 윈도우

device_id + metric 조합별로 최근 N개 값을 시계열 순으로 유지.
score = Unix timestamp (float), value = 측정값 (str)

Redis key 구조:
  sensa:ml:{device_id}:{metric}:win  → ZSET (score=timestamp, member="ts:value")
"""
import time
import redis
from django.conf import settings

WINDOW_SIZE = 60   # 윈도우 최대 포인트 수
_KEY = "sensa:ml:{device_id}:{metric}:win"
_TTL = 600  # 10분 TTL (비활성 센서 자동 정리)

_pool = None


def _client() -> redis.Redis:
    global _pool
    if _pool is None:
        host_tuple = settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0]
        if isinstance(host_tuple, (tuple, list)):
            host, port = host_tuple
            _pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
        else:
            _pool = redis.ConnectionPool.from_url(host_tuple, decode_responses=True)
    return redis.Redis(connection_pool=_pool)


def push(device_id: str, metric: str, value: float, ts: float | None = None) -> None:
    """값 하나를 윈도우에 추가. WINDOW_SIZE 초과분은 가장 오래된 것부터 제거."""
    ts = ts or time.time()
    key = _KEY.format(device_id=device_id, metric=metric)
    member = f"{ts}:{value}"
    r = _client()
    pipe = r.pipeline()
    pipe.zadd(key, {member: ts})
    # 오래된 항목 제거 (최신 WINDOW_SIZE 개만 유지)
    pipe.zremrangebyrank(key, 0, -(WINDOW_SIZE + 1))
    pipe.expire(key, _TTL)
    pipe.execute()


def get_values(device_id: str, metric: str) -> list[float]:
    """시간 오름차순으로 정렬된 float 값 목록 반환."""
    key = _KEY.format(device_id=device_id, metric=metric)
    members = _client().zrange(key, 0, -1)
    result = []
    for m in members:
        try:
            _, v = m.split(":", 1)
            result.append(float(v))
        except (ValueError, IndexError):
            pass
    return result


def size(device_id: str, metric: str) -> int:
    key = _KEY.format(device_id=device_id, metric=metric)
    return _client().zcard(key)
