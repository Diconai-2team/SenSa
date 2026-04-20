from django.db import models


SENSOR_TYPE_CHOICES = [
    ('gas', '가스'),
    ('power', '전력'),
    ('temperature', '온도'),
    ('motion', '동작'),
]

STATUS_CHOICES = [
    ('normal', '정상'),
    ('caution', '주의'),
    ('danger', '위험'),
]


class Device(models.Model):
    """센서 디바이스 — x, y는 이미지 내부 좌표"""
    device_id       = models.CharField(max_length=50, unique=True)
    device_name     = models.CharField(max_length=100)
    sensor_type     = models.CharField(max_length=20, choices=SENSOR_TYPE_CHOICES, default='gas')
    x               = models.FloatField(default=0)
    y               = models.FloatField(default=0)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='normal')
    last_value      = models.FloatField(null=True, blank=True)
    last_value_unit = models.CharField(max_length=20, blank=True, default='')
    is_active       = models.BooleanField(default=True)

    class Meta:
        ordering = ['device_id']

    def __str__(self):
        return f"{self.device_name} ({self.device_id})"


class SensorData(models.Model):
    """센서 측정값 히스토리"""
    device      = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='data')
    co          = models.FloatField(null=True, blank=True)
    h2s         = models.FloatField(null=True, blank=True)
    co2         = models.FloatField(null=True, blank=True)
    o2          = models.FloatField(null=True, blank=True)
    temperature = models.FloatField(null=True, blank=True)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='normal')
    timestamp   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['device', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.device.device_name} @ {self.timestamp}"
