"""
geofence/zone_lifecycle.py — 동적 위험구역 생성·진화·만료·승격

[Phase B] zone 생성·진화·만료
[Phase C] tier 승격 (tentative → confirmed → critical)

[알림 통합]
    동적 zone 도 GeoFence 인스턴스 (is_dynamic=True) 이므로,
    기존 alerts.services.geofence_utils 가 작업자 진입을 자동 판정.
"""
from datetime import timedelta
from django.utils import timezone

from geofence.models import GeoFence
from geofence.diffusion import diffusion_radius, GAS_MOLAR_MASS
from geofence.polygon_utils import circle_polygon, build_zone_polygon
from geofence.anomaly_detector import has_anomaly


# ── Tier 별 TTL (초) ──
TIER_TTL_SECONDS = {
    'tentative': 300,     # 5분
    'confirmed': 1800,    # 30분
    'critical':  3600,    # 60분
}

# 초기 zone 반경 산출용 가상 경과 시간
INITIAL_ELAPSED_SEC = 10.0

# 승격 조건
MIN_CONFIRMING_FOR_CONFIRMED = 1   # tentative → confirmed
MIN_CONFIRMING_FOR_CRITICAL  = 3   # confirmed → critical


# ─────────────────────────────────────────
# zone 생성
# ─────────────────────────────────────────

def create_dynamic_zone(
    source_device,
    gas_type: str,
    trigger_source: str = 'manual',
    risk_level: str = 'high',
    name: str = None,
) -> GeoFence:
    """잠정 동적 zone 생성 (Tier 1 = tentative)."""
    initial_radius = diffusion_radius(gas_type, INITIAL_ELAPSED_SEC)
    polygon = circle_polygon(source_device.x, source_device.y, initial_radius)
    expires_at = timezone.now() + timedelta(seconds=TIER_TTL_SECONDS['tentative'])

    if name is None:
        name = f"[자동] {source_device.device_id} {gas_type.upper()} 확산"

    zone = GeoFence.objects.create(
        name=name,
        zone_type='danger',
        description=f"TTM 발동 — {trigger_source}",
        risk_level=risk_level,
        polygon=polygon,
        is_active=True,
        is_dynamic=True,
        source_device=source_device,
        gas_type=gas_type.lower(),
        tier='tentative',
        current_radius_px=initial_radius,
        trigger_source=trigger_source,
        expires_at=expires_at,
    )

    # Phase I-1: 이벤트 발행
    from geofence.events import on_zone_created
    on_zone_created(zone)

    return zone


# ─────────────────────────────────────────
# zone 시간 진화
# ─────────────────────────────────────────

def _rebuild_polygon(zone: GeoFence) -> None:
    """source + confirmed_devices 좌표와 current_radius_px 로 polygon 재생성."""
    if not zone.source_device:
        return
    centers = [(zone.source_device.x, zone.source_device.y)]
    for d in zone.confirmed_devices.all():
        centers.append((d.x, d.y))

    radius = zone.current_radius_px or 0
    zone.polygon = build_zone_polygon(centers, radius)


def _scale_polygon_around_center(polygon, cx, cy, scale_factor):
    """polygon 의 각 점을 (cx, cy) 중심으로 scale_factor 배 확대.

    hull 모양 유지하면서 비율로 키움. scale_factor=1.0 면 동일.
    """
    if not polygon or scale_factor <= 0:
        return polygon
    return [
        [
            cx + (p[0] - cx) * scale_factor,
            cy + (p[1] - cy) * scale_factor,
        ]
        for p in polygon
    ]


def update_zone_radius(zone: GeoFence) -> float:
    """단일 zone 의 반경을 시간 진화로 갱신.

    Returns:
        새 반경 (px).
    """
    if not zone.is_dynamic or not zone.is_active:
        return zone.current_radius_px or 0

    elapsed = (timezone.now() - zone.created_at).total_seconds()
    new_radius = diffusion_radius(zone.gas_type, elapsed)

    # 변화 없으면 skip
    if zone.current_radius_px and abs(new_radius - zone.current_radius_px) < 0.5:
        return new_radius

    # 시나리오 zone: hull 모양 유지하며 비율 확대
    # 일반 동적 zone: 기존 _rebuild_polygon (source + confirmed_devices 기반)
    is_scenario = (
        zone.trigger_source and zone.trigger_source.startswith('scenario_op_')
    )

    if is_scenario and zone.source_device and zone.current_radius_px:
        # [Phase Realism v2 — hull → 원형 전이 (시간 기반)]
        #
        # 그레이엄 확산은 source 중심 방사. 초기 hull 은 영향 sensor 분포에 따라
        # 비대칭일 수 있는데 (예: 모두 NE 쪽만), _scale_polygon_around_center 는
        # hull 모양을 보존한 채 비례 확대 → 초기 hull 영역 밖 sensor (예: SW)
        # 는 polygon 확장에 따라서도 영원히 검출 안 됨.
        #
        # 해결: zone elapsed 가 TRANSITION_ELAPSED_SEC 넘어가면 source 중심
        # 원형 polygon 으로 전환. created_at 은 LEAK_ELAPSED_SEC 만큼 과거로
        # 설정돼있어 elapsed = LEAK_ELAPSED_SEC + real_t.
        # op_multi (LEAK=90, TTL=180) → real_t=30 부터 원형 전이.
        # 시각 서사: 초기 sensor 군집 hull → 확산 진행 시 그레이엄 원형.
        from geofence.polygon_utils import circle_polygon
        sx, sy = zone.source_device.x, zone.source_device.y
        TRANSITION_ELAPSED_SEC = 120   # zone elapsed 이만큼 넘으면 원형 전이
        if elapsed > TRANSITION_ELAPSED_SEC:
            zone.polygon = circle_polygon(sx, sy, new_radius)
        else:
            scale = new_radius / zone.current_radius_px
            zone.polygon = _scale_polygon_around_center(
                zone.polygon, sx, sy, scale,
            )
    else:
        _rebuild_polygon(zone)

    zone.current_radius_px = new_radius
    zone.save(update_fields=['polygon', 'current_radius_px', 'last_updated_at'])

    # [Live 갱신] frontend 실시간 반영 — WebSocket publish
    try:
        from geofence.events import on_polygon_expanded
        on_polygon_expanded(zone, added_device_ids=[])
    except Exception:
        pass

    # [Phase Realism] 시나리오 zone 의 polygon 확장 시,
    # 새로 polygon 안에 들어온 sensor 자동 검출 + spike 큐잉
    if is_scenario:
        try:
            _detect_and_spike_new_sensors_in_scenario_zone(zone)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f'[update_zone_radius] new sensor detect failed: {e}'
            )

    return new_radius


def _detect_and_spike_new_sensors_in_scenario_zone(zone: GeoFence) -> int:
    """시나리오 zone polygon 확장 후, 새로 들어온 sensor 검출 + spike 큐잉.

    [흐름]
        1. 운영 sensor 전체 조회
        2. zone.confirmed_devices 에 없는 sensor 중
        3. zone.polygon 안에 들어온 것 찾기
        4. 거리 기반 spike_value 계산 + sustain_spike_task 큐잉
        5. zone.confirmed_devices.add() 로 추적

    Returns:
        새로 큐잉된 sensor 개수.
    """
    import math
    from devices.models import Device, SensorData
    from geofence.services import point_in_polygon
    from geofence.tasks_scenario import sustain_spike_task

    if not zone.source_device or not zone.polygon:
        return 0

    # 시나리오 별 SPIKE_VALUE / NOISE / TTL 매핑
    # (operational_*.py 의 클래스 변수와 일치)
    SCENARIO_PARAMS = {
        'op_multi':  {'spike': 70.0, 'noise': 7.0, 'ttl': 120},
        'op_single': {'spike': 50.0, 'noise': 5.0, 'ttl': 90},
        'op_h2s':    {'spike': 30.0, 'noise': 3.0, 'ttl': 90},
    }
    name_key = zone.trigger_source.replace('scenario_op_', '') if zone.trigger_source else ''
    params = SCENARIO_PARAMS.get(name_key, {'spike': 50.0, 'noise': 5.0, 'ttl': 90})
    MIN_SPIKE_RATIO = 0.4

    # 이미 spike 받는 sensor (confirmed_devices)
    already_spiking_ids = set(zone.confirmed_devices.values_list('id', flat=True))
    already_spiking_ids.add(zone.source_device.id)   # source 도 항상 포함

    # 운영 sensor 전체
    all_sensors = Device.objects.filter(
        sensor_type='gas', is_active=True,
    ).exclude(device_id__startswith='sensa_scenario_')

    # 새로 polygon 안에 들어온 sensor
    new_sensors = []
    for s in all_sensors:
        if s.id in already_spiking_ids:
            continue
        if point_in_polygon(s.x, s.y, zone.polygon):
            new_sensors.append(s)

    if not new_sensors:
        return 0

    # zone 의 gas + 남은 TTL 기반 max_steps
    gas = zone.gas_type or 'co'
    remaining_sec = (
        (zone.expires_at - timezone.now()).total_seconds()
        if zone.expires_at else params['ttl']
    )
    SPIKE_INTERVAL_SEC = 0.5
    max_steps = max(10, int(remaining_sec / SPIKE_INTERVAL_SEC) + 10)
    diffusion_r = zone.current_radius_px or 400

    source = zone.source_device
    queued = 0
    for s in new_sensors:
        # 거리 기반 spike_value 차등
        dist = math.hypot(s.x - source.x, s.y - source.y)
        proximity = max(0.0, 1.0 - dist / diffusion_r)
        ratio = MIN_SPIKE_RATIO + (1 - MIN_SPIKE_RATIO) * proximity
        target_spike = params['spike'] * ratio

        # base_value: 직전 normal SensorData 의 가스값
        last_normal = SensorData.objects.filter(
            device=s, status='normal',
        ).order_by('-timestamp').first()
        base_v = getattr(last_normal, gas, None) if last_normal else None
        if base_v is None or base_v >= target_spike:
            base_v = target_spike * 0.3

        sustain_spike_task.apply_async(args=[
            zone.id, s.id, gas,
            target_spike, params['noise'], SPIKE_INTERVAL_SEC,
            max_steps, 0, float(base_v), 30.0,
        ])
        zone.confirmed_devices.add(s)
        queued += 1

    import logging
    logging.getLogger(__name__).info(
        f'[zone={zone.id}] 확장으로 새 sensor {queued}개 spike 큐잉: '
        f'{[s.device_id for s in new_sensors]}'
    )
    return queued


def update_all_active_zones() -> int:
    """활성 동적 zone 모두 반경 갱신."""
    zones = GeoFence.objects.filter(
        is_dynamic=True,
        is_active=True,
    ).select_related('source_device')

    count = 0
    for zone in zones:
        update_zone_radius(zone)
        count += 1
    return count


# ─────────────────────────────────────────
# zone 만료
# ─────────────────────────────────────────

def expire_zones() -> int:
    """expires_at 도래한 zone 들을 비활성화."""
    from geofence.events import on_zone_expired

    now = timezone.now()
    expired_zones = list(GeoFence.objects.filter(
        is_dynamic=True,
        is_active=True,
        expires_at__lte=now,
    ))
    count = len(expired_zones)

    for zone in expired_zones:
        zone.is_active = False
        zone.save(update_fields=['is_active', 'last_updated_at'])
        on_zone_expired(zone)

    return count


# ─────────────────────────────────────────
# 정상 회복 기반 자동 만료 (사용자 요청)
# ─────────────────────────────────────────

# source sensor 의 최근 N건 데이터가 모두 normal 이면 회복으로 판정
RECOVERY_CHECK_COUNT = 5


def expire_recovered_zones() -> int:
    """source sensor 데이터가 정상 회복된 동적 zone 을 자동 만료.

    조건:
        - is_dynamic=True (시스템 생성 zone 만)
        - is_active=True
        - source_device 존재
        - source sensor 의 최근 RECOVERY_CHECK_COUNT 건 모두 status='normal'

    사용자가 직접 그린 정적 zone (is_dynamic=False) 또는 source_device 가
    없는 zone 은 영향 받지 않음.

    Returns:
        만료 처리된 zone 수.
    """
    from devices.models import SensorData
    from geofence.events import on_zone_expired

    candidates = GeoFence.objects.filter(
        is_dynamic=True,
        is_active=True,
        source_device__isnull=False,
    ).select_related('source_device')

    recovered = []
    for zone in candidates:
        recent = list(SensorData.objects.filter(
            device=zone.source_device,
        ).order_by('-timestamp')[:RECOVERY_CHECK_COUNT])

        if len(recent) < RECOVERY_CHECK_COUNT:
            continue   # 데이터 부족 — 판정 보류

        if all(sd.status == 'normal' for sd in recent):
            recovered.append(zone)

    for zone in recovered:
        zone.is_active = False
        zone.save(update_fields=['is_active', 'last_updated_at'])
        on_zone_expired(zone)

    return len(recovered)


# ─────────────────────────────────────────
# Phase C — Tier 승격
# ─────────────────────────────────────────

def _upgrade_to_confirmed(zone: GeoFence) -> None:
    """tentative → confirmed 승격."""
    from geofence.events import on_tier_upgraded
    from_tier = zone.tier
    zone.tier = 'confirmed'
    zone.expires_at = timezone.now() + timedelta(
        seconds=TIER_TTL_SECONDS['confirmed']
    )
    _rebuild_polygon(zone)
    zone.save()
    on_tier_upgraded(zone, from_tier, 'confirmed')


def _upgrade_to_critical(zone: GeoFence) -> None:
    """confirmed → critical 승격."""
    from geofence.events import on_tier_upgraded
    from_tier = zone.tier
    zone.tier = 'critical'
    zone.risk_level = 'critical'
    zone.expires_at = timezone.now() + timedelta(
        seconds=TIER_TTL_SECONDS['critical']
    )
    _rebuild_polygon(zone)
    zone.save()
    on_tier_upgraded(zone, from_tier, 'critical')


def check_tier_upgrade(zone: GeoFence) -> str:
    """zone 의 이웃 센서들이 확산을 확인하는지 검사 + tier 승격.

    [흐름]
        1. zone 의 current_radius_px 내 이웃 센서 조회
        2. 각 이웃의 잔차 검사 → 이상이면 confirmed_devices 에 추가
        3. 누적 확인 센서 수에 따라 tier 결정

    Returns:
        'upgraded_to_confirmed' | 'upgraded_to_critical' | 'unchanged'
    """
    if not zone.is_active or not zone.is_dynamic:
        return 'unchanged'

    # [시나리오 격리] 시나리오 zone 은 tier 자동 승격 안 함.
    # 자동 승격 시 expires_at 이 critical(3600s) / confirmed(1800s) 로 연장돼
    # ZONE_TTL_SEC(90~120s) 시연 의도와 충돌.
    if zone.trigger_source and zone.trigger_source.startswith('scenario_op_'):
        return 'unchanged'

    if zone.tier == 'critical':
        return 'unchanged'   # 최상위, 더 올라갈 곳 없음

    # 현재 반경 내 이웃 센서
    from devices.neighbor_graph import get_neighbors_within_devices

    radius = zone.current_radius_px or 0
    if radius <= 0:
        return 'unchanged'

    candidates = get_neighbors_within_devices(zone.source_device.id, radius)
    if not candidates:
        return 'unchanged'

    # 이상 신호 보이는 이웃 추가
    already_confirmed_ids = set(
        zone.confirmed_devices.values_list('id', flat=True)
    )
    newly_confirmed = []
    for device, _dist in candidates:
        if device.id in already_confirmed_ids:
            continue
        if has_anomaly(device, zone.gas_type):
            newly_confirmed.append(device)

    if newly_confirmed:
        zone.confirmed_devices.add(*newly_confirmed)

    # tier 결정
    total = zone.confirmed_devices.count()

    if total >= MIN_CONFIRMING_FOR_CRITICAL and zone.tier != 'critical':
        _upgrade_to_critical(zone)
        return 'upgraded_to_critical'

    if zone.tier == 'tentative' and total >= MIN_CONFIRMING_FOR_CONFIRMED:
        _upgrade_to_confirmed(zone)
        return 'upgraded_to_confirmed'

    # confirmed_devices 만 추가됐고 tier 변경 없는 경우에도 polygon 재생성
    if newly_confirmed:
        _rebuild_polygon(zone)
        zone.save(update_fields=['polygon', 'last_updated_at'])
        from geofence.events import on_polygon_expanded
        on_polygon_expanded(zone, [d.device_id for d in newly_confirmed])

    return 'unchanged'


def check_all_active_zones_upgrade() -> dict:
    """모든 활성 동적 zone 에 대해 승격 검사."""
    zones = GeoFence.objects.filter(
        is_dynamic=True,
        is_active=True,
    ).exclude(tier='critical').select_related('source_device')

    result = {'upgraded_to_confirmed': 0, 'upgraded_to_critical': 0}
    for zone in zones:
        outcome = check_tier_upgrade(zone)
        if outcome in result:
            result[outcome] += 1
    return result


# ─────────────────────────────────────────
# tick — 통합 시간 진행
# ─────────────────────────────────────────

def tick(check_upgrade: bool = True) -> dict:
    """한 번의 시간 진행 (반경 갱신 + 만료 + 정상 회복 만료 + 승격 검사).

    Args:
        check_upgrade: False 시 승격 검사 skip (성능/디버깅용)

    Returns:
        {'updated': N, 'expired': M, 'recovered': R,
         'upgraded_to_confirmed': X, 'upgraded_to_critical': Y}
    """
    expired = expire_zones()
    recovered = expire_recovered_zones()    # ← 정상 회복 자동 만료
    updated = update_all_active_zones()

    upgrade_result = {'upgraded_to_confirmed': 0, 'upgraded_to_critical': 0}
    if check_upgrade:
        upgrade_result = check_all_active_zones_upgrade()

    return {
        'updated': updated,
        'expired': expired,
        'recovered': recovered,
        **upgrade_result,
    }



# ═════════════════════════════════════════════════════════════
# [C-3b-1] Phase L (TTM 사전 경고) 코드 완전 제거.
#   - check_forecast_trigger() 함수
#   - scan_forecast_warnings() 함수
#   - FORECAST_SCAN_GASES, FORECAST_TRIGGER_RISK_LEVEL 상수
#   - geofence.ai.ttm_engine 의존
# Isolation Forest 기반 분석기 (geofence/if_analyzer.py, C-3b-2) 로 대체.
# ═════════════════════════════════════════════════════════════
