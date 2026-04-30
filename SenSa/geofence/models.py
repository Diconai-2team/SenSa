from django.db import models
# 모델 필드 타입(CharField, JSONField, BooleanField 등)을 정의하기 위한 ORM 모듈


ZONE_TYPE_CHOICES = [
# zone_type 필드의 선택 가능한 값 — alerts.services._classify_state가 이 값으로 작업자 상태 분류
    ('danger', '위험'),
    # 위험 구역 — 작업자 진입 시 'danger' 상태로 격상
    ('caution', '주의'),
    # 주의 구역 — 작업자 진입 시 'caution' 상태로 격상
    ('restricted', '출입금지'),
    # 출입금지 구역 — 작업자 진입 시 'critical' 상태로 격상 (alerts에서 가장 높은 우선순위)
    # restricted는 zone_type 중 유일하게 4단계 사다리(safe<caution<danger<critical) 최상위로 매핑됨
]

RISK_LEVEL_CHOICES = [
# risk_level 필드의 선택 가능한 값 — UI 표시용 메타데이터 (실제 알람 레벨 결정엔 zone_type 사용)
# ⚠️ alerts.ALARM_LEVEL_CHOICES와 별개의 분류 — 통합/매핑 관계 명시 안 됨
    ('low', '낮음'),
    ('medium', '보통'),
    ('high', '높음'),
    ('critical', '심각'),
]


class GeoFence(models.Model):
    """위험 구역 — polygon은 [[x,y], ...] 이미지 내부 좌표"""
    # 공장 평면도 위에 그려진 다각형 위험 구역 1개를 나타내는 엔티티
    # devices.Device.geofence FK와 alerts.Alarm.geofence FK가 모두 이 모델을 참조
    
    name        = models.CharField(max_length=100)
    # 지오펜스 이름 — '용접 작업장', '고압가스 보관실' 등 운영자가 부여
    # alerts._build_message에서 알람 본문에 이 이름이 노출됨
    zone_type   = models.CharField(max_length=20, choices=ZONE_TYPE_CHOICES, default='danger')
    # 구역 종류 — alerts._classify_state가 작업자 상태 결정에 사용하는 핵심 필드
    # default='danger' — 운영자가 신규 등록 시 누락하면 가장 안전한 쪽(엄격한 판정)으로 fallback
    description = models.TextField(blank=True, default='')
    # 구역 설명 — 운영자 메모용 자유 텍스트 (관리/감사 추적용)
    risk_level  = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, default='high')
    # 위험도 메타데이터 — UI 표시/정렬 보조용
    # ⚠️ alerts 알람 발행 로직에선 사용 안 됨 — 정보 표시 목적
    polygon     = models.JSONField(default=list)
    # 다각형 정점 좌표 배열 — [[x1,y1], [x2,y2], ...] 형태 저장
    # 이미지 내부 픽셀 좌표 — devices.Device.x/y와 동일 좌표계
    # services.point_in_polygon이 이 데이터로 점-다각형 포함 판정 (Ray Casting)
    # ⚠️ JSONField라 SQL 레벨 공간 쿼리 불가 — PostGIS 같은 공간 DB 미사용
    #    PostgreSQL이 아니면 JSONField 인덱싱 효과 제한적
    is_active   = models.BooleanField(default=True)
    # 활성화 여부 — False면 ViewSet의 queryset에서 제외 (논리 삭제)
    # 물리 삭제 안 하는 이유: alerts.Alarm.geofence FK가 SET_NULL이지만,
    # 과거 알람이 어느 지오펜스에서 발생했는지 추적성 보존하고 싶은 운영 요구
    created_at  = models.DateTimeField(auto_now_add=True)
    # 생성 시각 — auto_now_add로 INSERT 시 자동 채움
    # ⚠️ updated_at 필드 없음 — 지오펜스 수정 이력 추적 불가
    #    이미지 좌표 기반 시스템에서 평면도 변경 시 polygon 재정의가 필요한데 변경 추적 어려움

    class Meta:
        ordering = ['-created_at']
        # 기본 정렬: 최신 등록이 먼저 — admin/API 응답에서 새로 만든 지오펜스가 위에

    def __str__(self):
        # admin/shell에서 객체를 읽기 좋은 형태로 표시
        return f"[{self.zone_type}] {self.name}"
        # '[restricted] 고압가스 보관실' 형태 — zone_type 한눈에 보임