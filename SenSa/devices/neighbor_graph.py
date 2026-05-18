"""
devices/neighbor_graph.py — 센서 근접도 메모리 캐시

모듈 레벨 dict 기반 lazy load.
첫 호출 시 DB 에서 가스 센서 좌표를 모두 읽어와 거리 행렬을 계산해 캐시.

센서 10대 규모에서 edge < 100 개로, 메모리 캐시로 충분.
Phase D 시나리오 생성기 단계에서 가상 센서가 추가될 경우
DB 테이블 (SensorNeighborGraph) 도입을 재검토.

[사용 예]
    from devices.neighbor_graph import get_neighbors_within
    from geofence.diffusion import diffusion_radius

    radius = diffusion_radius('co', 30)
    neighbors = get_neighbors_within(sensor.id, radius)
    # [(target_id, 거리px), ...] 거리 오름차순
"""
import math
from typing import Optional


# ── 모듈 레벨 캐시 ──
_cache: dict = {}            # {source_id: {target_id: distance_px}}
_cache_loaded: bool = False


def _load_cache() -> None:
    """가스 센서 전체 거리 행렬을 계산하여 캐시."""
    from devices.models import Device

    global _cache, _cache_loaded

    devices = list(
        Device.objects
        .filter(sensor_type='gas', is_active=True)
        .only('id', 'device_id', 'x', 'y')
    )

    new_cache = {}
    for d1 in devices:
        new_cache[d1.id] = {}
        for d2 in devices:
            if d1.id == d2.id:
                continue
            dx = d1.x - d2.x
            dy = d1.y - d2.y
            new_cache[d1.id][d2.id] = math.sqrt(dx * dx + dy * dy)

    _cache = new_cache
    _cache_loaded = True


def _ensure_loaded() -> None:
    """캐시 미로드 시 자동 로드."""
    if not _cache_loaded:
        _load_cache()


def invalidate_neighbor_cache() -> None:
    """캐시 무효화. 센서 추가/위치 변경 시 호출.

    다음 조회 시 자동 재로드.
    """
    global _cache, _cache_loaded
    _cache = {}
    _cache_loaded = False


def get_distance(source_id: int, target_id: int) -> Optional[float]:
    """두 센서 간 거리 (px). 캐시에 없으면 None.

    자기 자신 (source == target) 도 None 반환.
    """
    _ensure_loaded()
    return _cache.get(source_id, {}).get(target_id)


def get_neighbors_within(
    source_id: int,
    radius_px: float,
) -> list[tuple[int, float]]:
    """source 센서 기준 radius_px 내의 (target_id, 거리) 목록.

    Returns:
        거리 오름차순 정렬된 리스트.
    """
    _ensure_loaded()
    edges = _cache.get(source_id, {})
    within = [
        (tid, dist) for tid, dist in edges.items()
        if dist <= radius_px
    ]
    within.sort(key=lambda x: x[1])
    return within


def get_neighbors_within_devices(
    source_id: int,
    radius_px: float,
) -> list[tuple['Device', float]]:
    """get_neighbors_within 과 동일하지만 Device 인스턴스로 반환.

    Device 객체 필요한 경우에만 사용 (DB 추가 쿼리 발생).
    """
    from devices.models import Device

    within = get_neighbors_within(source_id, radius_px)
    if not within:
        return []

    target_ids = [tid for tid, _ in within]
    devices_by_id = {
        d.id: d for d in Device.objects.filter(id__in=target_ids)
    }
    return [
        (devices_by_id[tid], dist)
        for tid, dist in within
        if tid in devices_by_id
    ]


def cache_stats() -> dict:
    """디버깅용 캐시 상태 조회."""
    return {
        'loaded': _cache_loaded,
        'source_count': len(_cache),
        'total_edges': sum(len(v) for v in _cache.values()),
    }
