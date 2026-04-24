from django.db import models


ZONE_TYPE_CHOICES = [
    ('open',       '개방구역'),    # 제한 없는 일반 공간
    ('monitored',  '상시감시'),    # 진입 가능, 상시 모니터링
    ('hazardous',  '유해구역'),    # 유해 환경, 보호구 착용 필수
    ('restricted', '출입금지'),    # 허가 없이 진입 금지
]

class GeoFence(models.Model):
    """위험 구역 — polygon은 [[x,y], ...] 이미지 내부 좌표"""
    name        = models.CharField(max_length=100)
    zone_type   = models.CharField(max_length=20, choices=ZONE_TYPE_CHOICES, default='open')
    description = models.TextField(blank=True, default='')
    polygon     = models.JSONField(default=list)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.zone_type}] {self.name}"
