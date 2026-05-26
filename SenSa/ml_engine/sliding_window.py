"""
ml_engine/sliding_window.py — Redis ZSET 기반 슬라이딩 윈도우

device_id + metric 조합별로 최근 N개 값을 시계열 순으로 유지.
score = Unix timestamp (float), value = 측정값 (str)

Redis key 구조:
  sensa:ml:{device_id}:{metric}:win  → ZSET (score=timestamp, member="ts:value")
"""
import threading
import time
import redis
from django.conf import settings

WINDOW_SIZE = 60   # 윈도우 최대 포인트 수 (dev: 60포인트×3초=3분 / 운영: 60포인트×60초=1시간)
_KEY = "sensa:ml:{device_id}:{metric}:win"
_TTL = 600  # 10분 TTL (비활성 센서 자동 정리) [운영 전환 시] → 7200 (2시간, 1분 주기 기준 60틱 버퍼)

_pool = None
_pool_lock = threading.Lock()   # 첫 연결 생성 시 레이스 컨디션 방지


def _client() -> redis.Redis:
    """
    Redis 클라이언트 반환 (ConnectionPool 재사용).

    _pool_lock + double-checked locking 으로 멀티스레드 환경에서
    ConnectionPool 이 중복 생성되는 레이스 컨디션 방지.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:   # 락 획득 후 재확인 (double-check)
                host_tuple = settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0]
                if isinstance(host_tuple, (tuple, list)):
                    host, port = host_tuple
                    _pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
                else:
                    _pool = redis.ConnectionPool.from_url(host_tuple, decode_responses=True)
    return redis.Redis(connection_pool=_pool)


import logging as _logging
_logger = _logging.getLogger(__name__)


def push(device_id: str, metric: str, value: float, ts: float | None = None) -> None:
    """값 하나를 윈도우에 추가. WINDOW_SIZE 초과분은 가장 오래된 것부터 제거.

    [수정] Redis 연결 실패 시 경고 로그 후 무시 — state_store 와 동일 정책.
    """
    try:
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
    except Exception as exc:
        _logger.warning("[sliding_window] push(%s, %s) Redis 오류 — 무시: %s", device_id, metric, exc)


def get_values(device_id: str, metric: str) -> list[float]:
    """시간 오름차순으로 정렬된 float 값 목록 반환.

    [수정] Redis 연결 실패 시 빈 리스트 반환 — 호출 측은 MIN_WINDOW_POINTS 미만으로
    처리해 DB fallback 경로로 자연스럽게 이어진다.
    """
    try:
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
    except Exception as exc:
        _logger.warning("[sliding_window] get_values(%s, %s) Redis 오류 — 빈 리스트 반환: %s", device_id, metric, exc)
        return []


def size(device_id: str, metric: str) -> int:
    """[수정] Redis 연결 실패 시 0 반환."""
    try:
        key = _KEY.format(device_id=device_id, metric=metric)
        return _client().zcard(key)
    except Exception as exc:
        _logger.warning("[sliding_window] size(%s, %s) Redis 오류 — 0 반환: %s", device_id, metric, exc)
        return 0
