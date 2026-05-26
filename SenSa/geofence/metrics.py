"""
geofence/metrics.py — GeoFence 비즈니스 메트릭 정의 [P4-C, 8차 신규]

prometheus_client 모듈 레벨 정의 — django-prometheus /metrics 에 자동 노출.

사용처:
  geofence/events.py — _emit() 안에서 zone_event_total.inc()
  Gauge — 매 /metrics scrape 시점에 콜백으로 DB 카운트 (set_function)
"""
from prometheus_client import Counter, Gauge

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
