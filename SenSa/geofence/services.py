"""
geofence/services.py
지오펜스 내부 판별 — Ray Casting 알고리즘

점(x, y)에서 오른쪽으로 무한히 뻗는 광선이
polygon의 변(edge)과 홀수 번 교차하면 내부, 짝수 번이면 외부.
"""

# 이 파일의 핵심: 점-다각형 포함 판정 — 컴퓨터 그래픽스/GIS의 고전 알고리즘
# 시스템 전체에서 가장 자주 호출되는 함수 중 하나 (작업자/센서마다 매 평가에 호출됨)


def point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """
    polygon: [[x1,y1], [x2,y2], ...] 형태의 꼭짓점 배열
    반환: True(내부) / False(외부)
    """
    # Ray Casting (광선 캐스팅) 알고리즘 구현 — Jordan Curve Theorem 기반
    # 시간복잡도 O(n), 공간복잡도 O(1) — 정점 개수에 선형 비례

    n = len(polygon)
    if n < 3:
        return False
        # 다각형 최소 정점 3개 — 미만이면 영역 정의 불가능 (선분/점은 면적 0)
        # alerts._find_containing_geofences/alerts._find_sensor_geofence가 이 가드 의지

    inside = False
    # 누적 토글 변수 — 광선이 변과 교차할 때마다 뒤집어 마지막에 짝/홀 판정
    # 홀수번 교차 → True (내부), 짝수번 교차 → False (외부)
    j = n - 1
    # j는 "이전 정점" 인덱스 — 첫 반복(i=0)에선 마지막 정점과 첫 정점을 잇는 변부터 검사
    # 다각형이 닫혀있다고 가정 (마지막 정점 → 첫 정점 자동 연결)

    for i in range(n):
        # 모든 정점을 한 번씩 순회하면서 (이전 정점 j, 현재 정점 i) 변을 검사
        xi, yi = polygon[i]
        # 현재 정점 좌표
        xj, yj = polygon[j]
        # 이전 정점 좌표

        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        ):
            # 두 조건이 모두 참일 때만 inside 토글
            # 조건 1 (yi > y) != (yj > y):
            #   변의 두 끝점이 점의 y 기준선을 사이에 두고 있는지 — 광선이 변을 가로지를 가능성 검사
            #   (둘 다 위 또는 둘 다 아래면 광선이 안 닿음)
            # 조건 2 x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            #   광선(점에서 오른쪽 방향)이 변의 교차점보다 왼쪽에 있는지 — 실제로 교차하는지 확인
            #   교차점의 x좌표를 직선 보간으로 계산 후 점의 x와 비교
            # ⚠️ 정확히 정점 위에 점이 있을 때 (x=xi 또는 y=yi) edge case 처리 미명시
            #    Ray Casting 표준 구현에서 흔한 한계 — 비결정적 결과 가능
            # ⚠️ 부동소수점 연산 — 매우 가까운 거리에서 오판정 가능 (epsilon 미사용)
            inside = not inside
            # 교차 발생 → inside 뒤집기 (홀짝 토글)

        j = i
        # 다음 반복을 위해 j 갱신 — 현재 i가 다음 반복의 j(이전 정점)이 됨

    return inside
    # 모든 변 검사 완료 후 최종 inside 값이 결과
