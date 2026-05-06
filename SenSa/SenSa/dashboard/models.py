from django.db import models


class MapImage(models.Model):
    """공장 평면도 이미지"""
    image       = models.ImageField(upload_to='maps/')
    name        = models.CharField(max_length=100, blank=True, default='지도')
    width       = models.IntegerField(default=0)
    height      = models.IntegerField(default=0)
    is_active   = models.BooleanField(default=True)
    sort_order  = models.IntegerField(default=0, help_text='페이지네이션 순서 (작은 값이 먼저)')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'uploaded_at']

    def __str__(self):
        return f"{self.name} ({self.width}x{self.height})"
