"""
geofence/scenarios/sudden_leak.py — Phase D-2 SuddenLeak 시나리오.

[목적]
    다른 가스 도메인 임계값 검증. CO 외 가스에서도 시스템이 정확히
    동작하는지 확인. H2S 는 RESIDUAL_ABS_LIMIT=5 (CO 의 1/4) 로 더 민감.

[MultiLeak 와의 차이]
    - 가스: H2S (vs CO)
    - 도메인 임계: 5 ppm (vs 20 ppm)
    - baseline/spike 절대값 더 낮음 (H2S 운영 범위)
    - source 좌표 다름 (격리)
    - 확산 속도 다름: relative_velocity(h2s) ≈ 0.92 (M=34.08, 공기보다 약간 느림)
      → initial_radius ≈ 1.5 × 0.92 × 10 ≈ 13.8 px

[시나리오 순서]
    MultiLeak 동일 — 이웃 3개로 critical 승격 검증.

[기대 결과]
    MultiLeak 동일 — 다른 가스/임계에서도 동일하게 동작 확인.
"""
from geofence.scenarios.base import ScenarioBase
from geofence.zone_lifecycle import create_dynamic_zone, tick


class SuddenLeakScenario(ScenarioBase):
    """H2S 급격 누출 → critical 승격 검증 (다른 가스 도메인 임계 검증)."""

    name = 'sudden_leak'
    description = ('급격 누출 시나리오 — H2S 가스 (RESIDUAL_ABS_LIMIT=5) '
                   '+ 이웃 3개 잔차 detect → critical 도달 검증')

    # ── 시나리오 파라미터 ──
    GAS = 'h2s'
    BASELINE_VAL = 0.5    # 정상 H2S ppm (운영 평탄 구간)
    SPIKE_VAL = 30.0      # 잔차 29.5, RESIDUAL_ABS_LIMIT(h2s)=5 안전 초과
    SOURCE_XY = (3400.0, 1500.0)   # 평면도 우측 빈 영역
    NEIGHBOR_XY_LIST = [
        (3405.0, 1500.0),   # 동 5px (H2S 초기 반경 ~13.8 px 내)
        (3400.0, 1505.0),   # 남 5px
        (3400.0, 1495.0),   # 북 5px
    ]
    BASELINE_COUNT = 10
    SPIKE_COUNT = 3

    def setup(self) -> None:
        # 1. source + 이웃 3개
        self.source = self.create_test_device(
            'sudden_source',
            x=self.SOURCE_XY[0], y=self.SOURCE_XY[1],
        )
        self.neighbors = []
        for i, (nx, ny) in enumerate(self.NEIGHBOR_XY_LIST):
            n = self.create_test_device(
                f'sudden_nbr_{i + 1}', x=nx, y=ny,
            )
            self.neighbors.append(n)

        # 2. 캐시 무효화
        from devices.neighbor_graph import invalidate_neighbor_cache
        invalidate_neighbor_cache()

        # 3. baseline (모든 device)
        self.inject_baseline(
            self.source, self.GAS, self.BASELINE_VAL,
            count=self.BASELINE_COUNT,
        )
        for n in self.neighbors:
            self.inject_baseline(
                n, self.GAS, self.BASELINE_VAL,
                count=self.BASELINE_COUNT,
            )

    def run(self) -> None:
        # 1. spike (모든 device)
        self.inject_spike(
            self.source, self.GAS, self.SPIKE_VAL,
            count=self.SPIKE_COUNT,
        )
        for n in self.neighbors:
            self.inject_spike(
                n, self.GAS, self.SPIKE_VAL,
                count=self.SPIKE_COUNT,
            )

        # 2. zone 생성
        zone = create_dynamic_zone(
            source_device=self.source,
            gas_type=self.GAS,
            trigger_source='scenario_sudden_leak',
            name=f"[시나리오] sudden_leak {self.GAS.upper()}",
        )
        self.created_zone_ids.append(zone.id)

        # 3. 시간 압축
        from geofence.zone_lifecycle import INITIAL_ELAPSED_SEC
        self.age_zone(zone, seconds=INITIAL_ELAPSED_SEC)

        # 4. tick → 3개 이웃 모두 잔차 detect → critical
        tick(check_upgrade=True)

    def expected(self) -> dict:
        return {
            'zones_created':   1,
            'final_tier':      'critical',
            'event_types':     ['created', 'upgraded_to_critical'],
            'critical_count':  1,
            'confirmed_count': 0,
        }
