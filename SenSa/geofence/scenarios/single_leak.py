"""
geofence/scenarios/single_leak.py — Phase D-1 SingleLeak 시나리오.

[목적]
    R&D 계획서 핵심 요구사항 "평소 안전한 곳도 가스 누출 시 즉시 위험구역
    자동 형성" 의 가장 기본 패턴 검증. 단일 가스 누출원 → confirmed 승격.

[시나리오 순서]
    1. 인공 가스 센서 2개 생성 (source, neighbor — 8px 거리)
    2. 두 센서 baseline (정상 CO 12 ppm) 사전 주입 — 500~1700초 전
    3. 두 센서 spike (CO 60 ppm) 주입 — 5~7초 전
    4. zone 수동 생성 (source 기준, 초기 반경 ~15px)
    5. tick → check_tier_upgrade → neighbor 잔차 detect → confirmed 승격

[기대 결과]
    - GeoFence 1개 (final_tier = 'confirmed')
    - ZoneEvent 'created' + 'upgraded_to_confirmed' 발생
    - critical 미발생 (이웃 1개 < MIN_CONFIRMING_FOR_CRITICAL=3)

[수치 근거]
    - GAS=CO, RESIDUAL_ABS_LIMIT(co) = 20
    - 잔차 = spike avg(60) - baseline avg(12) = 48
      → threshold 20 안전 마진 28 (함정 #2 회피)
    - 이웃 거리 8 px, 초기 반경 ≈ V_BASE(1.5) × v_rel(CO≈1.017) × elapsed(10)
                              ≈ 15.3 px (이웃 안에 포함)
    - timestamp: baseline 500~1700초 전 / spike 5~7초 전
      → LOOKBACK_RECENT_SEC=300 윈도우 분리 (함정 #1 회피)
"""
from geofence.scenarios.base import ScenarioBase
from geofence.zone_lifecycle import create_dynamic_zone, tick


class SingleLeakScenario(ScenarioBase):
    """단일 가스 누출원 → confirmed 승격 검증."""

    name = 'single_leak'
    description = ('단일 가스 누출원 → confirmed 승격 검증 '
                   '(이웃 센서 1개 잔차 확인, critical 미발생)')

    # ── 시나리오 파라미터 ──
    GAS = 'co'
    BASELINE_VAL = 12.0   # 정상 CO ppm (운영 평균 수준)
    SPIKE_VAL = 60.0      # 잔차 48, RESIDUAL_ABS_LIMIT(co)=20 안전 초과
    SOURCE_XY = (2000.0, 1500.0)
    NEIGHBOR_XY = (2008.0, 1500.0)    # 8 px 거리 (초기 반경 ~15 px 내).
    # 운영 가스 센서 클러스터 (x:434-1271, y:516-953) 와 분리.
    # 평면도 (3840×2088) 안 빈 영역 — 화면에서 시각화 가능.
    # 시나리오 셋 일렬 배치: SingleLeak(2000) / MultiLeak(2700) / Sudden(3400)
    BASELINE_COUNT = 10
    SPIKE_COUNT = 3

    def setup(self) -> None:
        # 1. source + neighbor device 확보
        self.source = self.create_test_device(
            'leak_source',
            x=self.SOURCE_XY[0], y=self.SOURCE_XY[1],
        )
        self.neighbor = self.create_test_device(
            'leak_neighbor',
            x=self.NEIGHBOR_XY[0], y=self.NEIGHBOR_XY[1],
        )

        # 2. 이웃 캐시 무효화 (다음 조회 시 새 좌표로 자동 재로드)
        from devices.neighbor_graph import invalidate_neighbor_cache
        invalidate_neighbor_cache()

        # 3. baseline 데이터 주입 (두 센서 모두)
        self.inject_baseline(
            self.source, self.GAS, self.BASELINE_VAL,
            count=self.BASELINE_COUNT,
        )
        self.inject_baseline(
            self.neighbor, self.GAS, self.BASELINE_VAL,
            count=self.BASELINE_COUNT,
        )

    def run(self) -> None:
        # 1. recent spike 주입 (두 센서 모두 잔차 임계 초과)
        self.inject_spike(
            self.source, self.GAS, self.SPIKE_VAL,
            count=self.SPIKE_COUNT,
        )
        self.inject_spike(
            self.neighbor, self.GAS, self.SPIKE_VAL,
            count=self.SPIKE_COUNT,
        )

        # 2. zone 생성 (source 기준)
        zone = create_dynamic_zone(
            source_device=self.source,
            gas_type=self.GAS,
            trigger_source='scenario_single_leak',
            name=f"[시나리오] single_leak {self.GAS.upper()}",
        )
        self.created_zone_ids.append(zone.id)

        # 3. 시간 경과 시뮬레이션 — 운영의 Celery beat 30s tick 누적을 압축.
        #    zone 생성 직후 elapsed≈0 이면 update_zone_radius 가 반경을 0
        #    으로 줄여 이웃 검색이 빈 리스트가 됨. INITIAL_ELAPSED_SEC 만큼
        #    aging 하면 반경이 초기 15px 로 유지되어 이웃 검색 정상.
        from geofence.zone_lifecycle import INITIAL_ELAPSED_SEC
        self.age_zone(zone, seconds=INITIAL_ELAPSED_SEC)

        # 4. tick → update_zone_radius → check_tier_upgrade
        #    → neighbor 잔차 detect → confirmed 승격
        tick(check_upgrade=True)

    def expected(self) -> dict:
        return {
            'zones_created':   1,
            'final_tier':      'confirmed',
            'event_types':     ['created', 'upgraded_to_confirmed'],
            'critical_count':  0,
            'confirmed_count': 1,
        }
