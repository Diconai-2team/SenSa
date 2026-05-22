"""
geofence/scenarios/operational_multi.py — 다중 누출 (Phase J).

[시나리오 의미]
    "중심부 sensor 부근에서 가스 누출 발생. 300초 진행됨 (5분)."
    → 확산 반경 R_MAX(400px) cap 까지 도달
    → 중심부라 운영 sensor 다수 (3~5개) 자동 detect
    → 영향 sensor 거리 차등 spike
    → convex hull polygon (sensor 들 자연 둘러쌈)
    → critical tier 도달 (MIN_CONFIRMING_FOR_CRITICAL=3 충족 가능)

[시각 효과]
    화면 중앙에 큰 다각형 zone (영향 sensor 들 둘러쌈).
    각 영향 sensor 마커 caution 색상.
    R&D 평가: "한 지점 누출이 확산되며 다수 sensor 영향, 위험 구역 자동 형성"
    SFR-004-06/07 핵심 시연.
"""
import math
from typing import Optional

from devices.models import Device

from .operational_base import OperationalScenarioBase


class OperationalMultiLeak(OperationalScenarioBase):
    """중심부 sensor 강한 누출 — 다수 sensor 자동 영향."""

    name = 'op_multi'
    description = ('중심부 운영 sensor 1개 강한 누출 (5분 진행) '
                   '→ 큰 확산, 다수 sensor 자동 영향 → critical zone')

    GAS = 'co'
    SPIKE_VALUE = 70.0           # 더 강한 spike (잔차 큰 영향)
    SPIKE_NOISE = 7.0
    SPIKE_INTERVAL_SEC = 0.5
    ZONE_TTL_SEC = 180           # 3분 — 확산 단계별 검증 시간 확보
    LEAK_ELAPSED_SEC = 30        # 6차 — zone 크기 평면도 비례 적정 (radius 시작 61px → 180s 후 427px, sensor_02 검출 유지)

    POLYGON_MARGIN_PX = 60       # 큰 zone 외곽 여유

    def pick_source_sensor(self) -> Optional[Device]:
        """평균 거리 가장 작은 (중심부) sensor 자동 선택.

        중심부라 R_MAX=400px 안에 다른 sensor 다수 포함 → 다중 영향.
        """
        sensors = self._get_operational_sensors()
        if not sensors:
            return None

        if len(sensors) == 1:
            return sensors[0]

        # 평균 거리 최소 = 가장 중심부
        return min(
            sensors,
            key=lambda s: self._avg_distance_to_others(
                s, [o for o in sensors if o.id != s.id],
            ),
        )
