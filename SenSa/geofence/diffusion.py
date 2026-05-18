"""
geofence/diffusion.py — 그레이엄 확산 법칙 기반 위험 반경 계산

    v_A / v_B = sqrt(M_B / M_A)
    → 분자량이 작은 기체는 빨리 확산.

본 모듈은 무풍·이상 조건 가정. 운영 단계에서 환기·풍향 보정은
별도 phase 에서 추가 (Pasquill-Gifford 등).

기존 geofence/services.py 의 point_in_polygon 과 함께,
동적 위험구역 시스템의 두 핵심 계산 모듈 중 하나.
"""
import math


# 가스별 분자량 (g/mol)
GAS_MOLAR_MASS = {
    'nh3': 17.03,
    'co':  28.01,
    'o2':  32.00,
    'h2s': 34.08,
    'co2': 44.01,
    'no2': 46.01,
    'o3':  48.00,
    'so2': 64.07,
    'voc': 78.11,
}

M_AIR = 28.97                # 공기 평균 분자량
V_BASE_PX_PER_SEC = 2.0      # 기준 확산 속도 (시연 가시성 + 시간 검증 균형)
R_MAX = 700.0               # 최대 반경 cap (px)


def relative_velocity(gas_type: str) -> float:
    """공기 대비 가스 상대 확산 속도. M 이 작을수록 큼.

    미등록 가스는 공기와 같다고 보고 1.0 반환.
    """
    M = GAS_MOLAR_MASS.get(gas_type.lower(), M_AIR)
    return math.sqrt(M_AIR / M)


def diffusion_radius(gas_type: str, elapsed_sec: float) -> float:
    """가스 종류·경과 시간으로부터 이론 확산 반경 (px).

    Args:
        gas_type: 'co', 'h2s' 등 GAS_MOLAR_MASS 키
        elapsed_sec: zone 생성 후 경과 시간 (초)

    Returns:
        반경 (px). R_MAX 상한 적용.
    """
    if elapsed_sec < 0:
        elapsed_sec = 0
    r = V_BASE_PX_PER_SEC * relative_velocity(gas_type) * elapsed_sec
    return min(r, R_MAX)


def gas_reach_time(gas_type: str, target_distance_px: float) -> float:
    """특정 거리에 가스가 도달하기까지 걸리는 시간 (초).

    diffusion_radius 의 역함수. 이웃 센서가 확산을 감지할 예상 시점 계산용.
    """
    if target_distance_px <= 0:
        return 0
    v = V_BASE_PX_PER_SEC * relative_velocity(gas_type)
    if v <= 0:
        return float('inf')
    return target_distance_px / v
