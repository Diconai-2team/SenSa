"""
geofence/scenarios/operational_single.py — 단일 누출 (Phase J).

[시나리오 의미]
    "외곽 sensor 부근에서 가스 누출 발생. 60초 진행됨."
    → 확산 반경 ~91px (CO 60초)
    → 외곽이라 다른 sensor 거의 도달 못 함
    → 영향 sensor 1~2개 (대부분 source 만)
    → 정원 또는 작은 hull zone
    → tentative 또는 confirmed tier

[시각 효과]
    화면 외곽에 작은 빨간 zone + 1~2개 sensor 마커 caution 색상.
    R&D 평가: "단일 sensor 단독 누출, 인접 sensor 영향 없음" 시연.
"""
import math
from typing import Optional

from devices.models import Device

from .operational_base import OperationalScenarioBase


class OperationalSingleLeak(OperationalScenarioBase):
    """외곽 sensor 단일 누출 — 격리된 영향권."""

    name = 'op_single'
    description = ('외곽 운영 sensor 1개 단일 누출 (60초 진행) '
                   '→ 작은 zone, 영향 sensor 최소')

    GAS = 'co'
    SPIKE_VALUE = 50.0
    SPIKE_NOISE = 5.0
    SPIKE_INTERVAL_SEC = 0.5
    ZONE_TTL_SEC = 90
    LEAK_ELAPSED_SEC = 60        # CO 60초 → 확산 반경 ~91px

    def pick_source_sensor(self) -> Optional[Device]:
        """평균 거리 가장 큰 (외곽) sensor 자동 선택.

        외곽이라 다른 sensor 들과 거리가 멀어 확산 반경 91px 안에 들어오는
        sensor 거의 없음 → 단독 누출 시각화.
        """
        sensors = self._get_operational_sensors()
        if not sensors:
            return None

        if len(sensors) == 1:
            return sensors[0]

        # 평균 거리 최대 = 가장 외곽
        return max(
            sensors,
            key=lambda s: self._avg_distance_to_others(
                s, [o for o in sensors if o.id != s.id],
            ),
        )
