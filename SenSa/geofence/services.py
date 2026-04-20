"""
geofence/services.py
지오펜스 내부 판별 — Ray Casting 알고리즘

점(x, y)에서 오른쪽으로 무한히 뻗는 광선이
polygon의 변(edge)과 홀수 번 교차하면 내부, 짝수 번이면 외부.
"""


def point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """
    polygon: [[x1,y1], [x2,y2], ...] 형태의 꼭짓점 배열
    반환: True(내부) / False(외부)
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1

    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside

        j = i

    return inside
