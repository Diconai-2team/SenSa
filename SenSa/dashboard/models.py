from django.db import models
# 모델 필드 타입(ImageField, CharField 등)을 정의하기 위한 ORM 모듈


class MapImage(models.Model):
    """공장 평면도 이미지"""
    # 시스템의 좌표계 기준이 되는 평면도 1장 — geofence/devices/workers의 (x,y)가 모두 이 이미지 위 픽셀 좌표
    # 동시에 1장만 활성화 — perform_create가 기존 활성을 비활성화하고 새 것만 활성화
    
    image       = models.ImageField(upload_to='maps/')
    # MEDIA_ROOT/maps/ 디렉터리에 이미지 파일 저장
    # ⚠️ ImageField는 Pillow 의존 — 패키지 설치 + 이미지 검증 필수
    # ⚠️ 파일 크기/포맷 제한 부재 — 큰 PSD 같은 파일도 업로드 가능
    name        = models.CharField(max_length=100, blank=True, default='지도')
    # 평면도 이름 — '1공장 1층', '용접실' 등 운영자 식별용
    # blank=True + default='지도' — 운영자가 이름 안 넣으면 일반 라벨
    width       = models.IntegerField(default=0)
    # 이미지 가로 픽셀 — 좌표계 범위 정의
    # ⚠️ 자동 추출 안 함 — perform_create에서 Pillow로 추출하거나 클라이언트가 명시 필요
    #    default=0이면 alerts/devices/workers의 (x,y) 검증 시 무의미한 기준
    height      = models.IntegerField(default=0)
    # 이미지 세로 픽셀
    is_active   = models.BooleanField(default=True)
    # 활성 평면도 여부 — 동시에 1장만 True
    # views.MapImageViewSet.perform_create가 기존 활성 모두 비활성화 후 새 것 활성화
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # 업로드 시각 — auto_now_add로 INSERT 시 자동
    # ⚠️ updated_at 부재 — 평면도 메타정보 수정 이력 추적 불가

    class Meta:
        ordering = ['-uploaded_at']
        # 기본 정렬 — 최신 업로드가 위 (admin/API 응답)

    def __str__(self):
        return f"{self.name} ({self.width}x{self.height})"
        # '1공장 1층 (1920x1080)' 형태