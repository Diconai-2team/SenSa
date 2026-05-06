"""
backoffice/geo_utils.py — 점-폴리곤 포함 판정

shapely 미설치 환경에서도 동작하도록 ray casting 알고리즘 직접 구현.
GeoFence.polygon 은 [[x, y], [x, y], ...] 형식의 단순 폴리곤.

성능: O(n_points × n_polygons). 본 시스템 규모 (수십 폴리곤, 수백 장비)
에선 충분. 대규모 환경은 R-tree (rtree 패키지) 권장.
"""
from __future__ import annotations


def point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """ray casting 방식. polygon = [[x,y], ...] 최소 3점.

    경계선 위 점은 구현체별로 다를 수 있음 — 본 구현은 짝수 교차로 처리.
    """
    if not polygon or len(polygon) < 3:
        return False
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def find_containing_geofence(x: float, y: float, geofences):
    """장비 (x, y) 가 어느 지오펜스 안에 있는지.
    여러 폴리곤 안에 동시에 있으면 첫 매치 반환 (zone_type 우선순위 적용).

    Args:
        geofences: GeoFence iterable (active 만 넘기는 게 좋음)

    Returns:
        매칭되는 GeoFence 인스턴스 또는 None
    """
    # 우선순위: danger > restricted > caution > 기타 (위험할수록 먼저 매칭)
    PRIORITY = {'danger': 0, 'restricted': 1, 'caution': 2}
    matches = []
    for g in geofences:
        if point_in_polygon(x, y, g.polygon):
            matches.append(g)
    if not matches:
        return None
    matches.sort(key=lambda g: PRIORITY.get(g.zone_type, 99))
    return matches[0]
