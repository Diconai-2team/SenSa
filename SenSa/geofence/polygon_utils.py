"""
geofence/polygon_utils.py — 위험구역 polygon 형태 생성

3가지 케이스:
- 1점 (source 만): circle polygon
- 2점 (source + 확인 1): capsule polygon
- 3점+ (source + 확인 N): convex hull + margin

Andrew's monotone chain 으로 convex hull 직접 구현 (scipy 의존성 회피).
"""
import math


CIRCLE_POLYGON_POINTS = 16
ARC_POINTS_PER_CENTER = 12      # capsule/hull margin 시 각 중심점 주변 분할 수


def circle_polygon(
    cx: float,
    cy: float,
    radius: float,
    n_points: int = CIRCLE_POLYGON_POINTS,
) -> list:
    """단일 중심 + 반경으로 원형 polygon. Phase B 와 동일."""
    points = []
    for i in range(n_points):
        angle = 2 * math.pi * i / n_points
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        points.append([round(x, 2), round(y, 2)])
    return points


def _arc_points_around(
    cx: float,
    cy: float,
    radius: float,
    n: int = ARC_POINTS_PER_CENTER,
) -> list:
    """중심 주변에 작은 원의 점들. convex hull 입력으로 사용."""
    return [
        (
            cx + radius * math.cos(2 * math.pi * i / n),
            cy + radius * math.sin(2 * math.pi * i / n),
        )
        for i in range(n)
    ]


def _convex_hull(points: list) -> list:
    """Andrew's monotone chain — 외부 의존성 없는 convex hull.

    Args:
        points: [(x, y), ...]

    Returns:
        외곽선 점들, 반시계방향 정렬.
    """
    pts = sorted(set(map(tuple, points)))
    if len(pts) <= 1:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    # lower hull
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    # upper hull
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def hull_with_margin(centers: list, margin_radius: float) -> list:
    """각 중심점 주변에 margin_radius 의 작은 원을 그리고 전체의 convex hull.

    centers 개수에 따라:
    - 1개: 원형과 동일 결과
    - 2개: capsule 형태 (두 원 + 중간 연결)
    - 3개+: 다각형 + margin

    Args:
        centers: [(x, y), ...]
        margin_radius: 각 중심점 주변 안전 여유 반경

    Returns:
        polygon 좌표 배열 [[x, y], ...]
    """
    if not centers:
        return []

    # 각 중심 주변 원의 점들 모두 합치기
    all_points = []
    for cx, cy in centers:
        all_points.extend(_arc_points_around(cx, cy, margin_radius))

    # convex hull
    hull = _convex_hull(all_points)
    return [[round(x, 2), round(y, 2)] for x, y in hull]


def build_zone_polygon(centers: list, radius: float) -> list:
    """zone 의 모든 confirmed 센서 좌표 + radius 로 polygon 생성.

    centers 길이에 따라 적절한 모양 선택:
    - 1: circle
    - 2: capsule (hull_with_margin 으로 자연 처리)
    - 3+: convex hull + margin
    """
    if len(centers) == 1:
        cx, cy = centers[0]
        return circle_polygon(cx, cy, radius)
    return hull_with_margin(centers, radius)
