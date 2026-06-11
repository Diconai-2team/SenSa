"""
geofence/auto_trigger.py — 실데이터 위험 전이 → 동적 위험구역 자동 발동 (P-AZ)

[배경]
GeoFence 모델에는 trigger_source='threshold'(임계 초과) 선택지가 처음부터
정의돼 있었으나(geofence/models.py TRIGGER_SOURCE_CHOICES), 실데이터 수신
경로에서 이를 발동하는 배선이 없었다. 동적 zone 은 geofence 시나리오 API 와
관리 명령(trigger_test_zone)에서만 생성 가능했다.
이 모듈이 그 배선이다: devices/views.py 수신 경로에서 가스 danger '전이' 시
create_dynamic_zone(trigger_source='threshold') 을 호출한다.

[설계 원칙 — 수집 파이프라인 보호가 최우선]
1. 어떤 예외도 수신 경로로 전파하지 않음 (전부 흡수 + 로그).
   저장 게이트의 graceful degradation 정책과 동일.
2. classify_gas(팀원 영역)는 수정하지 않음 — GAS_THRESHOLDS 를 인터페이스로
   재사용해 '어떤 가스가 위험인지'만 이 모듈에서 판별.
3. 발동 조건: danger '전이' 시에만. 지속 danger 는 zone_lifecycle.tick 담당
   (반경 확장·tier 승격·만료는 기존 30초 beat tick 그대로 — 책임 분리 유지).
4. 중복 방지 2중:
   ① Redis 게이트 cache.add(SET NX EX, 원자적) — V자 진동(danger↔normal
      급반복)·다중 Pod 동시 전이로 인한 중복 발동 차단.
      캐시 장애 시엔 ② DB 검사가 중복 방지를 이어받는다.
   ② DB — 같은 device+gas 의 active 동적 zone 이 있으면 skip.
5. 대상: 가스 단방향 8종만. O2 는 제외 — O2 위험(결핍/과잉)은 '누출 확산'
   물리 모델(diffusion_radius, 분자량 √(M_air/M) 기반)이 성립하지 않음.
   전력(power) danger 도 동일 사유로 비대상.
"""
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

# danger 전이 1회당 게이트 창 — 같은 device+gas 재발동 최소 간격
AUTO_ZONE_GATE_SEC = 60

# 확산 모델 비대상 가스 (구간형 임계 — '누출' 의미 불성립)
_EXCLUDED = ('o2',)


def _worst_danger_gas(gas_values: dict):
    """danger 임계를 넘은 가스 중 초과 배율(값/임계)이 최대인 가스 키 반환.

    classify_gas 는 worst '상태'만 돌려주므로(팀원 영역, 무수정),
    '어떤 가스가' 위험인지는 여기서 GAS_THRESHOLDS 로 재판별한다.
    danger 가스가 없으면 None (예: O2 단독 위험).
    """
    from alerts.services.classifiers import GAS_THRESHOLDS

    worst_key, worst_ratio = None, 0.0
    for key, val in (gas_values or {}).items():
        if val is None or key in _EXCLUDED:
            continue
        t = GAS_THRESHOLDS.get(key)
        if not t:
            continue
        try:
            ratio = float(val) / float(t['danger'])
        except (TypeError, ValueError, ZeroDivisionError, KeyError):
            continue
        if ratio >= 1.0 and ratio > worst_ratio:
            worst_key, worst_ratio = key, ratio
    return worst_key


def maybe_trigger_zone(device, gas_values: dict,
                       observed_status: str, prev_status: str):
    """가스 danger '전이' 시 동적 zone 자동 발동. 예외 무전파(항상 안전).

    Returns:
        생성된 GeoFence 인스턴스 또는 None (비전이/중복/비대상/실패).
    """
    try:
        # danger 로의 '전이'만 — 지속 danger 는 tick 담당
        if observed_status != 'danger' or prev_status == 'danger':
            return None

        gas = _worst_danger_gas(gas_values)
        if gas is None:
            return None

        # ① Redis 게이트 (원자적 — 다중 Pod 창당 1회)
        try:
            if not cache.add(
                f'autozone:{device.device_id}:{gas}', 1, AUTO_ZONE_GATE_SEC
            ):
                return None
        except Exception:
            # 캐시 장애 → 발동은 계속 진행, 중복 방지는 ② DB 검사가 담당
            logger.warning("[auto-zone] 캐시 게이트 실패 — DB 검사로 폴백")

        # ② 같은 device+gas 의 active 동적 zone 존재 시 skip
        from geofence.models import GeoFence
        if GeoFence.objects.filter(
            source_device=device, gas_type=gas,
            is_dynamic=True, is_active=True,
        ).exists():
            return None

        from geofence.zone_lifecycle import create_dynamic_zone
        zone = create_dynamic_zone(
            device, gas,
            trigger_source='threshold',
            name=f"[자동] {device.device_id} {gas.upper()} 임계초과 확산",
        )
        logger.info(
            "[auto-zone] danger 전이 → 동적 zone 발동: device=%s gas=%s zone_id=%s",
            device.device_id, gas, zone.id,
        )
        return zone

    except Exception:
        # 어떤 실패도 수집 경로(devices/views.py)로 전파하지 않는다.
        logger.exception(
            "[auto-zone] 자동 발동 실패 — 수집 경로 영향 없음 (device=%s)",
            getattr(device, 'device_id', '?'),
        )
        return None
