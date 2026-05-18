"""
geofence/scenarios/operational_h2s.py — H2S 급격 누출 (Phase J).

[시나리오 의미]
    "임의 sensor 부근에서 H2S 급격 누출. 60초 진행."
    → H2S 확산 속도 CO 대비 약간 느림 (분자량 34 vs 28)
    → 확산 반경 ~83px (60초)
    → H2S 임계 5ppm 대비 SPIKE 25ppm = 5배 잔차
    → critical 등급 빠르게 도달 가능
"""
import random
from typing import Optional

from devices.models import Device

from .operational_base import OperationalScenarioBase


class OperationalH2SLeak(OperationalScenarioBase):
    """랜덤 sensor H2S 누출 — 가스 종별 시연용."""

    name = 'op_h2s'
    description = ('임의 운영 sensor H2S 누출 (60초 진행) — 가스 종별 시연')

    GAS = 'h2s'
    SPIKE_VALUE = 25.0           # H2S 임계 5의 5배
    SPIKE_NOISE = 2.5
    SPIKE_INTERVAL_SEC = 0.5
    ZONE_TTL_SEC = 90
    LEAK_ELAPSED_SEC = 60

    def pick_source_sensor(self) -> Optional[Device]:
        """랜덤 운영 sensor 1개."""
        sensors = self._get_operational_sensors()
        if not sensors:
            return None
        return random.choice(sensors)
