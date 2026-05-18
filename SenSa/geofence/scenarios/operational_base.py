"""
geofence/scenarios/operational_base.py — Phase J 운영 시나리오 베이스.

[Phase J 핵심 — SFR-004-06/07 충족]
    R&D 계획서 명시: "감지 센서를 기준으로 초기 위험 범위를 자동으로 지정하고,
    감지된 유해가스 종류에 따라 그레이엄 확산 법칙에 의해 계산된 확산 속도를
    적용 및 위험 지역의 범위를 동적으로 갱신"

[v3.1 → Phase J 변경]
    이전 v3.1:
        - pick_sensors() 미리 cluster 명시 선택
        - source 1개 기준 단순 정원 zone (radius hardcoded)
        - 모든 영향 sensor 동일 spike 강도
    Phase J:
        - pick_source_sensor() — 누출원 1개 자동 선택
        - diffusion_radius(gas, LEAK_ELAPSED_SEC) 로 확산 반경 자동 계산
        - 운영 sensor 전체에서 반경 안 들어오는 sensor 자동 detect
        - 거리 기반 spike 강도 차등 (가까울수록 강함)
        - zone polygon: 영향 sensor 2+ 시 convex hull, 1 시 정원

[시연 흐름]
    1. pick_source_sensor() — 누출원 1개
    2. compute_diffusion() — 확산 반경 + 영향 sensor 자동 산출 + spike 차등
    3. _create_zone() — convex hull (또는 정원) polygon
    4. _start_sustained_spike() — 각 영향 sensor 에 차등 spike Celery 큐잉
"""
import math
import random
from datetime import timedelta
from typing import List, Optional, Tuple

from django.utils import timezone

from devices.models import Device, SensorData
from geofence.diffusion import diffusion_radius, gas_reach_time


class OperationalScenarioBase:
    """운영 sensor 기반 시연 시나리오. 확산 모델로 영향 sensor 자동 산출."""

    name: str = ''
    description: str = ''

    # ── 가스 + spike ──
    GAS = 'co'
    SPIKE_VALUE = 50.0          # 누출원 sensor 의 spike 강도 (최대)
    SPIKE_NOISE = 5.0           # ± 노이즈
    SPIKE_INTERVAL_SEC = 0.5    # 주입 간격 (fastapi 대비 우세)
    MIN_SPIKE_RATIO = 0.4       # 확산 반경 끝 sensor 의 spike 강도 (40%)

    # ── 확산 모델 ──
    LEAK_ELAPSED_SEC = 60       # 누출 진행 가정 시간 → 확산 반경 결정
                                # CO 60s = ~91px, 300s = R_MAX(400)px

    # ── zone ──
    ZONE_TTL_SEC = 90           # zone 만료까지 시간
    POLYGON_MARGIN_PX = 50      # convex hull 외곽 여유
    MIN_ZONE_RADIUS_PX = 150    # 정원 zone 최소 반경 (인접 sensor 거리 ~114~140 보다 큼)
                                # 축척 고려: 평면도 3840×2088 에서 시연 가시성 확보

    def __init__(self):
        self.source_sensor: Optional[Device] = None
        self.affected: List[dict] = []          # [{'sensor', 'distance', 'reach_time', 'spike_value'}]
        self.created_zone_ids: List[int] = []
        self.diffusion_r: float = 0.0
        self._error: Optional[str] = None

    # ── 추상 — 하위 클래스 override ─────────────────────────────
    def pick_source_sensor(self) -> Optional[Device]:
        """누출원 sensor 1개 선택. 하위 클래스 override."""
        raise NotImplementedError

    # ── 운영 sensor 조회 (공통) ─────────────────────────────────
    @staticmethod
    def _get_operational_sensors() -> List[Device]:
        """운영 가스 sensor 전체 (시나리오 인공 device 제외)."""
        return list(Device.objects.filter(
            sensor_type='gas', is_active=True,
        ).exclude(device_id__startswith='sensa_scenario_'))

    @staticmethod
    def _avg_distance_to_others(s: Device, others: List[Device]) -> float:
        if not others:
            return 0.0
        return sum(
            math.hypot(s.x - o.x, s.y - o.y) for o in others
        ) / len(others)

    # ── 실행 ────────────────────────────────────────────────────
    def execute(self) -> dict:
        source = self.pick_source_sensor()
        if source is None:
            self._error = '누출원 sensor 선택 실패'
            return self._fail()
        self.source_sensor = source

        # 1. 확산 반경 계산
        self.diffusion_r = diffusion_radius(self.GAS, self.LEAK_ELAPSED_SEC)

        # 2. 영향 sensor 자동 detect + spike 차등
        self.affected = self._compute_affected(source, self.diffusion_r)
        if not self.affected:
            # 이론상 source 자체는 항상 distance=0 으로 포함됨
            self._error = '영향 sensor 산출 실패 (소스 누락)'
            return self._fail()

        try:
            zone_ids = self._create_zone()
            spike_info = self._start_sustained_spike()
        except Exception as e:
            self._error = f"{type(e).__name__}: {e}"
            return self._fail()

        # 응답
        return {
            'status': 'success',
            'name':           self.name,
            'source_sensor':  source.device_id,
            'source_xy':      (source.x, source.y),
            'gas':            self.GAS,
            'leak_elapsed_sec':   self.LEAK_ELAPSED_SEC,
            'diffusion_radius_px': round(self.diffusion_r, 1),
            'affected_sensors': [
                {
                    'device_id':      a['sensor'].device_id,
                    'distance_px':    round(a['distance'], 1),
                    'reach_time_sec': round(a['reach_time'], 1),
                    'spike_value':    round(a['spike_value'], 1),
                }
                for a in self.affected
            ],
            'affected_count':       len(self.affected),
            'zone_polygon_type':    'circle' if len(self.affected) == 1 else 'convex_hull',
            'zone_ids':             zone_ids,
            'zone_ttl_sec':         self.ZONE_TTL_SEC,
            'spike_interval_sec':   self.SPIKE_INTERVAL_SEC,
            'sustained_tasks_queued': spike_info['tasks_queued'],
        }

    def _fail(self) -> dict:
        return {
            'status': 'error',
            'name':   self.name,
            'error':  self._error or 'unknown',
        }

    # ── Phase J 핵심: 영향 sensor 자동 산출 ─────────────────────
    def _compute_affected(
        self, source: Device, diffusion_r: float,
    ) -> List[dict]:
        """확산 반경 안에 들어오는 운영 sensor 자동 detect + spike 차등.

        Returns:
            [
                {'sensor', 'distance', 'reach_time', 'spike_value'},
                ...
            ]
            distance 가장 가까운 순으로 정렬.
        """
        all_sensors = self._get_operational_sensors()
        results = []

        for s in all_sensors:
            dist = math.hypot(s.x - source.x, s.y - source.y)
            if dist > diffusion_r:
                continue

            # 거리 기반 spike 강도 (가까울수록 강함)
            # ratio: source=1.0, edge=MIN_SPIKE_RATIO
            if diffusion_r > 0:
                proximity = 1.0 - (dist / diffusion_r)   # 1.0 ~ 0
                ratio = self.MIN_SPIKE_RATIO + (1 - self.MIN_SPIKE_RATIO) * proximity
            else:
                ratio = 1.0

            results.append({
                'sensor':       s,
                'distance':     dist,
                'reach_time':   gas_reach_time(self.GAS, dist),
                'spike_value':  self.SPIKE_VALUE * ratio,
            })

        # 가까운 순 정렬
        results.sort(key=lambda r: r['distance'])
        return results

    # ── zone 생성 (Phase J 핵심: convex hull 또는 정원) ─────────
    def _create_zone(self) -> List[int]:
        """영향 sensor 분포에 따라 polygon 형태 자동 결정.

        - 1개 (source 만): 정원 (반경 = max(80, diffusion_r * 0.6))
        - 2+ : convex hull + margin
        """
        from geofence.zone_lifecycle import (
            create_dynamic_zone, INITIAL_ELAPSED_SEC,
        )
        from geofence.models import GeoFence
        from geofence.polygon_utils import (
            build_zone_polygon, circle_polygon, hull_with_margin,
        )

        source = self.source_sensor

        zone = create_dynamic_zone(
            source_device=source,
            gas_type=self.GAS,
            trigger_source=f'scenario_op_{self.name}',
            name=f"[시나리오] {self.name} {source.device_id}",
        )
        self.created_zone_ids.append(zone.id)

        # polygon 결정
        affected_count = len(self.affected)
        if affected_count <= 1:
            # source 단독 → 정원. 인접 sensor 도달 가능한 최소 반경 보장
            # (축척 고려: 운영 sensor 간 거리 ~114~140px 대비 충분히 큼)
            r = max(self.MIN_ZONE_RADIUS_PX, self.diffusion_r * 0.6)
            polygon = circle_polygon(source.x, source.y, r)
            radius_for_db = r
        else:
            # 다수 영향 sensor → convex hull + margin
            centers = [(a['sensor'].x, a['sensor'].y) for a in self.affected]
            polygon = hull_with_margin(centers, self.POLYGON_MARGIN_PX)
            radius_for_db = self.diffusion_r   # 메타용

        # zone 갱신
        # created_at 을 LEAK_ELAPSED_SEC 만큼 과거로 설정 →
        # update_zone_radius 가 elapsed=LEAK_ELAPSED_SEC 시점부터 계산 →
        # 첫 tick 에서 시작 radius 와 일관성 유지 (radius 축소 X)
        now = timezone.now()
        GeoFence.objects.filter(pk=zone.pk).update(
            created_at=now - timedelta(seconds=self.LEAK_ELAPSED_SEC),
            expires_at=now + timedelta(seconds=self.ZONE_TTL_SEC),
            current_radius_px=float(radius_for_db),
            polygon=polygon,
        )

        return self.created_zone_ids

    # ── spike 지속 주입 (각 영향 sensor 별 차등) ────────────────
    def _start_sustained_spike(self) -> dict:
        """각 영향 sensor 에 Celery sustain_spike_task 큐잉.

        spike_value 는 _compute_affected 에서 산출한 거리 기반 차등값.

        [Phase Realism]
            - base_value: 직전 normal SensorData 의 가스값 (점진 증가 시작점)
            - ramp_up_sec: 30초 동안 base → spike_value 선형 증가
            - zone.confirmed_devices: 이미 spike 받는 sensor 추적
              (update_zone_radius 가 새 sensor 검출 시 중복 방지)
        """
        from geofence.tasks_scenario import sustain_spike_task
        from geofence.models import GeoFence

        if not self.created_zone_ids:
            return {'tasks_queued': 0}

        zone_id = self.created_zone_ids[0]
        zone = GeoFence.objects.get(id=zone_id)
        max_steps = int(self.ZONE_TTL_SEC / self.SPIKE_INTERVAL_SEC) + 10

        for a in self.affected:
            sensor = a['sensor']
            # base_value: 직전 normal SensorData 의 가스값 (시작점)
            last_normal = SensorData.objects.filter(
                device=sensor, status='normal',
            ).order_by('-timestamp').first()
            base_v = getattr(last_normal, self.GAS, None) if last_normal else None
            if base_v is None or base_v >= a['spike_value']:
                base_v = a['spike_value'] * 0.3   # fallback (30% 시작)

            sustain_spike_task.apply_async(
                args=[
                    zone_id,
                    sensor.id,
                    self.GAS,
                    a['spike_value'],             # 목표 spike (거리 차등)
                    self.SPIKE_NOISE,
                    self.SPIKE_INTERVAL_SEC,
                    max_steps, 0,
                    float(base_v),                # 점진 증가 시작점
                    30.0,                         # ramp-up 30초
                ],
            )
            # zone 의 confirmed_devices 에 추가 (이미 spike 받는 sensor 추적)
            zone.confirmed_devices.add(sensor)

        return {'tasks_queued': len(self.affected)}

    # ── cleanup (전역 함수에서 zone 기반 일괄) ──────────────────
    def cleanup(self) -> dict:
        from geofence.models import GeoFence
        zone_count = GeoFence.objects.filter(
            id__in=self.created_zone_ids,
        ).delete()[0] if self.created_zone_ids else 0
        return {'deleted_zones': zone_count}


# ───────────────────────────────────────────────────────────────
# 전역 cleanup — name + trigger_source 기반
# ───────────────────────────────────────────────────────────────

def cleanup_all_operational_scenarios() -> dict:
    """API 호출용 일괄 정리.

    각 zone 마다 on_zone_expired 호출하여 WebSocket 통지 후 삭제.
    (frontend zone_live 가 'expired' 이벤트 받아 polygon 즉시 제거)
    """
    from geofence.models import GeoFence
    from geofence.events import on_zone_expired

    # 1. trigger_source 기반 zone
    zones_a = list(GeoFence.objects.filter(
        trigger_source__startswith='scenario_op_',
    ))
    # 2. name 기반 zone (legacy)
    zones_b = list(GeoFence.objects.filter(
        name__startswith='[시나리오]',
    ).exclude(id__in=[z.id for z in zones_a]))

    all_zones = zones_a + zones_b

    # WebSocket 'expired' 통지 후 delete
    for zone in all_zones:
        try:
            on_zone_expired(zone)
        except Exception:
            pass

    deleted = 0
    for zone in all_zones:
        zone.delete()
        deleted += 1

    return {
        'deleted_zones': deleted,
        'note': 'SensorData 는 LOOKBACK 5분 후 자연 회복',
    }
