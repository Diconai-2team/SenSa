"""
geofence/metrics.py — GeoFence 비즈니스 메트릭 정의 [P4-C, 8차 신규]

prometheus_client 모듈 레벨 정의 — django-prometheus /metrics 에 자동 노출.

사용처:
  geofence/events.py — _emit() 안에서 zone_event_total.inc()
  Gauge — 매 /metrics scrape 시점에 콜백으로 DB 카운트 (set_function)
"""
from prometheus_client import REGISTRY, Counter, Gauge
from prometheus_client.core import GaugeMetricFamily

# ─── Counter: zone 라이프사이클 이벤트 ───
#   event_type:
#     'created'             — 동적 zone 생성
#     'upgraded_to_<tier>'  — tentative → confirmed → critical 승격
#     'polygon_expanded'    — confirmed_devices 추가
#     'expired'             — TTL 만료로 비활성화
zone_event_total = Counter(
    'sensa_zone_event_total',
    'GeoFence 라이프사이클 이벤트 수 (created/upgraded/polygon_expanded/expired)',
    labelnames=('event_type',),
)

# ─── Gauge: 현재 활성 GeoFence 수 ───
# 라벨 없이 두 개 분리 — set_function 은 라벨 child 에 안 통하므로
# (prometheus_client 0.20 기준)
zone_active_static = Gauge(
    'sensa_zone_active_static',
    '활성 정적 GeoFence 수 (관리자가 그린 polygon)',
)
zone_active_dynamic = Gauge(
    'sensa_zone_active_dynamic',
    '활성 동적 GeoFence 수 (TTM/op_multi 자동 생성)',
)


def _count_active_static() -> int:
    """현재 활성 정적 zone 카운트 — 매 scrape 시점 callback."""
    from geofence.models import GeoFence
    return GeoFence.objects.filter(is_active=True, is_dynamic=False).count()


def _count_active_dynamic() -> int:
    """현재 활성 동적 zone 카운트 — 매 scrape 시점 callback."""
    from geofence.models import GeoFence
    return GeoFence.objects.filter(is_active=True, is_dynamic=True).count()


# scrape 시점에 lazy 호출 (Django 앱 ready 후 안전하게 ORM 접근)
zone_active_static.set_function(_count_active_static)
zone_active_dynamic.set_function(_count_active_dynamic)


# ═══════════════════════════════════════════════════════════
# 동적 zone 상태 Collector (G4 확산 반경 / G5 영향 센서 수)
# ═══════════════════════════════════════════════════════════
#   매 /metrics scrape 시점에 활성 동적 zone 별로:
#     - sensa_zone_radius_px         : 그레이엄 확산 현재 반경 (Phase J 핵심)
#     - sensa_zone_affected_sensors  : confirmed_devices 수 (영향 센서)
#   라벨: zone_id (+ radius 는 gas_type/tier).
#
#   set_function 은 단일 값만 가능 → 다중 zone(라벨) 게이지는 Collector 로 구현.
#   scrape 시점 조회라 만료된 zone 은 자동으로 series 에서 사라짐(stale 없음).
#   zone 카디널리티는 "동시 활성 동적 zone 수" 만큼이라 매우 낮음.

class ZoneStateCollector:
    """활성 동적 zone 의 확산 반경 + 영향 센서 수를 scrape 시점에 노출."""

    def collect(self):
        radius = GaugeMetricFamily(
            'sensa_zone_radius_px',
            '동적 zone 의 그레이엄 확산 현재 반경 (px). op_* 확산 추적용.',
            labels=['zone_id', 'gas_type', 'tier'],
        )
        affected = GaugeMetricFamily(
            'sensa_zone_affected_sensors',
            '동적 zone 의 영향(confirmed) 센서 수. op_multi 다중 확산 추적용.',
            labels=['zone_id', 'gas_type'],
        )
        try:
            from django.db.models import Count
            from geofence.models import GeoFence

            zones = (GeoFence.objects
                     .filter(is_active=True, is_dynamic=True)
                     .annotate(_n_confirmed=Count('confirmed_devices')))
            for z in zones:
                zid = str(z.id)
                gas = z.gas_type or ''
                radius.add_metric(
                    [zid, gas, z.tier or ''],
                    float(z.current_radius_px or 0.0),
                )
                affected.add_metric([zid, gas], float(z._n_confirmed))
        except Exception:
            # 수집 실패가 scrape 전체를 깨지 않도록 격리 — 부분 결과 노출
            pass
        yield radius
        yield affected


def _register_collectors():
    """중복 등록 방지하며 collector 등록 (테스트 다중 import 안전)."""
    try:
        REGISTRY.register(ZoneStateCollector())
    except ValueError:
        pass  # 이미 등록됨 (동일 메트릭 이름) — 무시


_register_collectors()
