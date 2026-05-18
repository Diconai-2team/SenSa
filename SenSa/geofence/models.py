"""
geofence/models.py — 위험 구역 (정적 + 동적 통합)

[변경 이력]
  Phase A: 동적 zone 지원을 위한 필드 확장
    - is_dynamic, source_device, confirmed_devices
    - gas_type, tier, current_radius_px, trigger_source
    - expires_at, last_updated_at

정적 zone (관리자 지정) 과 동적 zone (TTM 자동 발동) 을 한 모델로 통합.
polygon 필드는 두 경우 모두 [[x,y], ...] 형태로 통일되어, 기존
point_in_polygon 함수와 작업자 진입 판정 로직을 그대로 재사용 가능.
"""
from django.db import models


ZONE_TYPE_CHOICES = [
    ('normal', '정상'),
    ('caution', '주의'),
    ('danger', '위험'),
    ('restricted', '출입금지'),
]

RISK_LEVEL_CHOICES = [
    ('low', '낮음'),
    ('medium', '보통'),
    ('high', '높음'),
    ('critical', '심각'),
]

# ── Phase A 추가: 동적 zone 신뢰도 단계 ──
TIER_CHOICES = [
    ('', '— (정적)'),
    ('tentative', '잠정'),
    ('confirmed', '확인됨'),
    ('critical', '긴급'),
]

TRIGGER_SOURCE_CHOICES = [
    ('', '— (정적)'),
    ('manual', '관리자 지정'),
    ('threshold', '임계 초과'),
    ('ttm_anomaly', 'TTM 이상 탐지'),
    ('ttm_forecast', 'TTM 사전 경고'),
]


class GeoFence(models.Model):
    """위험 구역 — polygon은 [[x,y], ...] 이미지 내부 좌표

    is_dynamic=False (default): 관리자가 직접 그린 정적 polygon
    is_dynamic=True: TTM 이상 탐지 등으로 자동 생성된 동적 zone

    두 경우 모두 polygon 형태로 통일되어 진입 판정 로직 공유.
    """
    # ─── 기존 필드 (무수정) ───
    name        = models.CharField(max_length=100)
    zone_type   = models.CharField(max_length=20, choices=ZONE_TYPE_CHOICES, default='danger')
    description = models.TextField(blank=True, default='')
    risk_level  = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, default='high')
    polygon     = models.JSONField(default=list)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    # ─── Phase A 추가: 동적 zone 필드 (모두 nullable, 정적 zone 호환 유지) ───

    is_dynamic = models.BooleanField(
        default=False,
        db_index=True,
        help_text='동적으로 자동 생성된 zone 여부',
    )

    source_device = models.ForeignKey(
        'devices.Device',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='triggered_zones',
        help_text='동적 zone 발동 센서 (정적 zone 은 null)',
    )

    confirmed_devices = models.ManyToManyField(
        'devices.Device',
        blank=True,
        related_name='confirmed_in_zones',
        help_text='확산 확인된 인접 센서들 (Tier 2/3 승격 근거)',
    )

    gas_type = models.CharField(
        max_length=10,
        blank=True, default='',
        help_text='확산 계산용 가스 종류 (co, h2s, co2, ...)',
    )

    tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        blank=True, default='',
        help_text='동적 zone 신뢰도 단계',
    )

    current_radius_px = models.FloatField(
        null=True, blank=True,
        help_text='그레이엄 기반 현재 이론 반경 (동적 zone 만)',
    )

    trigger_source = models.CharField(
        max_length=20,
        choices=TRIGGER_SOURCE_CHOICES,
        blank=True, default='',
        help_text='동적 zone 발동 원인',
    )

    expires_at = models.DateTimeField(
        null=True, blank=True,
        db_index=True,
        help_text='자동 만료 시각 (동적 zone)',
    )

    last_updated_at = models.DateTimeField(
        auto_now=True,
        help_text='마지막 갱신 (반경 진화, tier 승격 등)',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'is_dynamic']),
            models.Index(fields=['source_device', 'is_active']),
        ]

    def __str__(self):
        if self.is_dynamic:
            tier_label = dict(TIER_CHOICES).get(self.tier, self.tier) or '?'
            return f"[동적-{tier_label}] {self.name}"
        return f"[{self.zone_type}] {self.name}"


# ─────────────────────────────────────────
# Phase I-1 — Zone 라이프사이클 이벤트 로깅
# ─────────────────────────────────────────

ZONE_EVENT_TYPE_CHOICES = [
    ('created',                'Zone 생성'),
    ('polygon_expanded',       'Polygon 확장 (이웃 추가)'),
    ('upgraded_to_confirmed',  'Tier 승격 → 확인됨'),
    ('upgraded_to_critical',   'Tier 승격 → 긴급'),
    ('expired',                'Zone 만료'),
]


class ZoneEvent(models.Model):
    """동적 zone 라이프사이클 이벤트 로그.

    zone 생성 / tier 승격 / polygon 확장 / 만료 시점에 기록.
    admin 에서 zone 이력 추적, 추후 realtime/외부 알림 발행의 입력.
    """
    zone = models.ForeignKey(
        GeoFence,
        on_delete=models.CASCADE,
        related_name='events',
    )
    event_type = models.CharField(
        max_length=30,
        choices=ZONE_EVENT_TYPE_CHOICES,
    )
    from_tier = models.CharField(max_length=20, blank=True, default='')
    to_tier = models.CharField(max_length=20, blank=True, default='')
    trigger_source = models.CharField(max_length=20, blank=True, default='')
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['zone', 'created_at']),
            models.Index(fields=['event_type', 'created_at']),
        ]

    def __str__(self):
        zone_name = self.zone.name if self.zone_id else '?'
        return f"[{self.event_type}] {zone_name} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
