from django.db import models


ZONE_TYPE_CHOICES = [
    ('danger', '위험'),
    ('caution', '주의'),
    ('restricted', '출입금지'),
]

RISK_LEVEL_CHOICES = [
    ('low', '낮음'),
    ('medium', '보통'),
    ('high', '높음'),
    ('critical', '심각'),
]


class GeoFence(models.Model):
    """위험 구역 — polygon은 [[x,y], ...] 이미지 내부 좌표"""
    name        = models.CharField(max_length=100)
    zone_type   = models.CharField(max_length=20, choices=ZONE_TYPE_CHOICES, default='danger')
    description = models.TextField(blank=True, default='')
    risk_level  = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, default='high')
    polygon     = models.JSONField(default=list)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.zone_type}] {self.name}"
