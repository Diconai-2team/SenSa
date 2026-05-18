"""
geofence/scenarios/multi_leak.py — Phase D-2 MultiLeak 시나리오.

[목적]
    R&D 계획서 요구사항 "다중 센서 확인 시 critical 승격" 검증.
    이웃 가스 센서 3개 모두 잔차 detect → MIN_CONFIRMING_FOR_CRITICAL=3
    충족 → tier 'tentative' 에서 'critical' 로 직점프.

[승격 흐름]
    check_tier_upgrade 안 분기 순서:
        1. total >= 3 + tier != 'critical'   → _upgrade_to_critical
        2. tier == 'tentative' + total >= 1  → _upgrade_to_confirmed

    이웃 3개가 한 tick 에 모두 confirmed_devices 로 추가되면 total=3
    이 되어 첫 분기에서 critical 직점프. 'upgraded_to_confirmed' 이벤트는
    발행되지 않음 — event_types 가 ['created', 'upgraded_to_critical'].

[시나리오 순서]
    1. source + 이웃 3개 (모두 ~6 px 거리, 초기 반경 ~15 px 내)
    2. 모든 device baseline + spike 주입
    3. zone 생성, age_zone(INITIAL_ELAPSED_SEC) 시간 압축
    4. tick(check_upgrade=True) — 이웃 3개 모두 detect → critical

[기대 결과]
    - GeoFence 1개 (final_tier='critical')
    - ZoneEvent 'created' + 'upgraded_to_critical' (confirmed 이벤트 없음)
    - critical_count=1, confirmed_count=0

[부수효과]
    'upgraded_to_critical' → events.py 의 `_notify_external_critical`
    → alerts.tasks.send_external_notification_task.delay() 큐잉.
    Celery worker 동시 동작 시 실제 Slack/Discord 발송.
    회귀 폭주 회피: SENSA_NOTIFY_DRY_RUN=true 환경변수로 실행.
"""
from geofence.scenarios.base import ScenarioBase
from geofence.zone_lifecycle import create_dynamic_zone, tick


class MultiLeakScenario(ScenarioBase):
    """이웃 3개 잔차 detect → critical 승격 검증."""

    name = 'multi_leak'
    description = ('다중 확인 센서 시나리오 — 이웃 3개 잔차 detect '
                   '→ critical 승격 (MIN_CONFIRMING_FOR_CRITICAL=3 충족)')

    # ── 시나리오 파라미터 ──
    GAS = 'co'
    BASELINE_VAL = 12.0
    SPIKE_VAL = 60.0      # 잔차 48, threshold 20 안전 마진 28
    SOURCE_XY = (2700.0, 1500.0)
    NEIGHBOR_XY_LIST = [
        (2706.0, 1500.0),   # 동 6px
        (2700.0, 1506.0),   # 남 6px
        (2700.0, 1494.0),   # 북 6px
    ]
    # 평면도 안 빈 영역. SingleLeak(2000)에서 700px 분리.
    BASELINE_COUNT = 10
    SPIKE_COUNT = 3

    def setup(self) -> None:
        # 1. source + 이웃 3개 device
        self.source = self.create_test_device(
            'multi_source',
            x=self.SOURCE_XY[0], y=self.SOURCE_XY[1],
        )
        self.neighbors = []
        for i, (nx, ny) in enumerate(self.NEIGHBOR_XY_LIST):
            n = self.create_test_device(
                f'multi_nbr_{i + 1}', x=nx, y=ny,
            )
            self.neighbors.append(n)

        # 2. 이웃 캐시 무효화
        from devices.neighbor_graph import invalidate_neighbor_cache
        invalidate_neighbor_cache()

        # 3. baseline 모두 주입 (4 devices × 10 = 40건)
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
        # 1. spike 모든 device (4 × 3 = 12건)
        self.inject_spike(
            self.source, self.GAS, self.SPIKE_VAL,
            count=self.SPIKE_COUNT,
        )
        for n in self.neighbors:
            self.inject_spike(
                n, self.GAS, self.SPIKE_VAL,
                count=self.SPIKE_COUNT,
            )

        # 2. zone 생성 (source 기준)
        zone = create_dynamic_zone(
            source_device=self.source,
            gas_type=self.GAS,
            trigger_source='scenario_multi_leak',
            name=f"[시나리오] multi_leak {self.GAS.upper()}",
        )
        self.created_zone_ids.append(zone.id)

        # 3. 시간 압축 — Phase D-1 함정 #11 회피
        from geofence.zone_lifecycle import INITIAL_ELAPSED_SEC
        self.age_zone(zone, seconds=INITIAL_ELAPSED_SEC)

        # 4. tick → 이웃 3개 모두 detect → total=3 → critical 직점프
        tick(check_upgrade=True)

    def expected(self) -> dict:
        return {
            'zones_created':   1,
            'final_tier':      'critical',
            # 첫 분기에서 critical 점프, confirmed 이벤트 발행 안 됨
            'event_types':     ['created', 'upgraded_to_critical'],
            'critical_count':  1,
            'confirmed_count': 0,
        }
