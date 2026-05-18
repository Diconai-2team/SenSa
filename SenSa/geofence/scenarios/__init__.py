"""
geofence.scenarios — Phase D 시나리오 생성기 패키지.

[등록 시나리오 - 두 종류]

A. 격리 시나리오 (회귀/CLI 전용, ScenarioBase 상속)
   인공 device 4~7개 생성, 평면도 밖 좌표, 자기완결 검증:
   - single_leak   : 단일 누출 → confirmed (D-1)
   - multi_leak    : 다중 누출 → critical 직점프 (D-2)
   - sudden_leak   : H2S 가스 → critical (D-2)

B. 운영 시나리오 (대시보드 시연용, OperationalScenarioBase 별도 베이스)
   운영 sensor (sensor_01~07) 그대로 사용, 실제 좌표, R&D 평가 시연:
   - op_single  : 운영 sensor 1개 단일 누출
   - op_multi   : cluster 3개 다중 누출 → critical
   - op_h2s     : 운영 sensor 1개 H2S 급격
"""
# ── 격리 시나리오 (D-1/D-2) ──
from .base import ScenarioBase
from .single_leak import SingleLeakScenario
from .multi_leak import MultiLeakScenario
from .sudden_leak import SuddenLeakScenario

# ── 운영 시나리오 (Phase Demo v2) ──
from .operational_base import (
    OperationalScenarioBase,
    cleanup_all_operational_scenarios,
)
from .operational_single import OperationalSingleLeak
from .operational_multi import OperationalMultiLeak
from .operational_h2s import OperationalH2SLeak


# ── 격리 시나리오 레지스트리 (CLI run_scenario / verify_*) ──
SCENARIO_REGISTRY = {
    SingleLeakScenario.name: SingleLeakScenario,
    MultiLeakScenario.name:  MultiLeakScenario,
    SuddenLeakScenario.name: SuddenLeakScenario,
}


# ── 운영 시나리오 레지스트리 (대시보드 패널 / op API 전용) ──
OP_SCENARIO_REGISTRY = {
    OperationalSingleLeak.name: OperationalSingleLeak,
    OperationalMultiLeak.name:  OperationalMultiLeak,
    OperationalH2SLeak.name:    OperationalH2SLeak,
}


def get_scenario(name: str) -> type:
    """격리 시나리오 lookup."""
    if name not in SCENARIO_REGISTRY:
        raise KeyError(
            f"unknown scenario '{name}'. available: {sorted(SCENARIO_REGISTRY)}"
        )
    return SCENARIO_REGISTRY[name]


def list_scenarios() -> list:
    """격리 시나리오 목록."""
    return [
        {'name': cls.name, 'description': cls.description}
        for cls in SCENARIO_REGISTRY.values()
    ]


def get_op_scenario(name: str) -> type:
    """운영 시나리오 lookup."""
    if name not in OP_SCENARIO_REGISTRY:
        raise KeyError(
            f"unknown op scenario '{name}'. "
            f"available: {sorted(OP_SCENARIO_REGISTRY)}"
        )
    return OP_SCENARIO_REGISTRY[name]


def list_op_scenarios() -> list:
    """운영 시나리오 목록."""
    return [
        {'name': cls.name, 'description': cls.description}
        for cls in OP_SCENARIO_REGISTRY.values()
    ]


__all__ = [
    # 격리
    'ScenarioBase',
    'SingleLeakScenario', 'MultiLeakScenario', 'SuddenLeakScenario',
    'SCENARIO_REGISTRY', 'get_scenario', 'list_scenarios',
    # 운영
    'OperationalScenarioBase',
    'OperationalSingleLeak', 'OperationalMultiLeak', 'OperationalH2SLeak',
    'OP_SCENARIO_REGISTRY', 'get_op_scenario', 'list_op_scenarios',
    'cleanup_all_operational_scenarios',
]
