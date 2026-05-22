"""
realtime/cache.py — Phase 3 최신 상태 캐시.

3단계 문서 5. 최신 상태 캐시:
  키 패턴 예시:
    sensor:latest:sensor_01
    worker:latest:worker_01
    alert:latest

용도: 관제 화면 첫 로드 시 DB 조회 대신 Redis 캐시 활용.
갱신: WebSocket publish 와 동시 (publishers.py 안에서 자동 호출).

Django 의 cache framework + Redis backend (settings.CACHES['default']) 사용.
Redis DB 2 — Celery (DB 0) 과 분리됨.
"""
from __future__ import annotations
from django.core.cache import cache

# 키 prefix — 캐시 key 충돌 방지
_SENSOR_PREFIX = 'sensor:latest:'
_WORKER_PREFIX = 'worker:latest:'
_ALERT_LATEST_KEY = 'alert:latest'

# TTL — settings.CACHES['default']['TIMEOUT'] 가 default. 명시적 override 가능.
_DEFAULT_TTL = 300   # 5분


# ═══════════════════════════════════════════════════════
# Sensor 최신 상태
# ═══════════════════════════════════════════════════════

def set_latest_sensor(device_id: str, data: dict, ttl: int = _DEFAULT_TTL) -> None:
    """센서 최신 상태 저장.

    data 예시: {'device_id', 'sensor_type', 'status', 'values': {...}, 'timestamp'}
    """
    cache.set(f'{_SENSOR_PREFIX}{device_id}', data, timeout=ttl)


def get_latest_sensor(device_id: str) -> dict | None:
    """센서 최신 상태 조회. 없으면 None."""
    return cache.get(f'{_SENSOR_PREFIX}{device_id}')


def get_all_latest_sensors(device_ids: list[str]) -> dict[str, dict]:
    """여러 sensor 의 최신 상태 한번에 조회. 없는 키는 결과에서 제외.

    Returns:
        {device_id: data, ...}
    """
    keys = [f'{_SENSOR_PREFIX}{d}' for d in device_ids]
    raw = cache.get_many(keys)
    result = {}
    for k, v in raw.items():
        device_id = k.replace(_SENSOR_PREFIX, '')
        result[device_id] = v
    return result


# ═══════════════════════════════════════════════════════
# Worker 최신 위치
# ═══════════════════════════════════════════════════════

def set_latest_worker(worker_id: str, data: dict, ttl: int = _DEFAULT_TTL) -> None:
    """작업자 최신 위치 저장.

    data 예시: {'worker_id', 'worker_name', 'x', 'y', 'movement_status', 'timestamp'}
    """
    cache.set(f'{_WORKER_PREFIX}{worker_id}', data, timeout=ttl)


def get_latest_worker(worker_id: str) -> dict | None:
    """작업자 최신 위치 조회. 없으면 None."""
    return cache.get(f'{_WORKER_PREFIX}{worker_id}')


# ═══════════════════════════════════════════════════════
# Alert 최신 상태 (선택)
# ═══════════════════════════════════════════════════════

def set_latest_alert(alarm_dict: dict, ttl: int = _DEFAULT_TTL) -> None:
    """가장 최근 알람 1개. 운영자 페이지 첫 로드 시 활용 가능."""
    cache.set(_ALERT_LATEST_KEY, alarm_dict, timeout=ttl)


def get_latest_alert() -> dict | None:
    return cache.get(_ALERT_LATEST_KEY)


# ═══════════════════════════════════════════════════════
# 디버그/운영 도구
# ═══════════════════════════════════════════════════════

def clear_sensor_cache(device_id: str = None) -> None:
    """캐시 삭제 (개별 또는 전체 sensor)."""
    if device_id:
        cache.delete(f'{_SENSOR_PREFIX}{device_id}')
    else:
        # 전체 sensor 캐시 삭제 — Redis 직접 명령 필요
        try:
            from django_redis import get_redis_connection
            conn = get_redis_connection('default')
            for key in conn.scan_iter(f'sensa:1:{_SENSOR_PREFIX}*'):
                conn.delete(key)
        except ImportError:
            # django_redis 미설치 시 — 개별 device_id 만 가능
            pass
