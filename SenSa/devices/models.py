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

    # ── 신규: 소속 지오펜스 ──
    # null=True → 지오펜스에 속하지 않은 센서도 허용 (바깥 공용 구역 등)
    # on_delete=SET_NULL → 지오펜스 삭제해도 센서는 남음 (센서 자체는 물리적으로 존재)
    # related_name='devices' → geofence.devices.all() 로 역참조
    # 앱 간 참조는 문자열 'geofence.GeoFence' 사용 (순환 import 방지)
    geofence = models.ForeignKey(
        'geofence.GeoFence',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='devices',
        help_text='이 센서가 속한 지오펜스 (없으면 공용 구역)'
    )
    
    class Meta:
        ordering = ['device_id']

    def __str__(self):
        return f"{self.device_name} ({self.device_id})"


class SensorData(models.Model):
    """센서 측정값 히스토리"""
    device      = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='data')
    co          = models.FloatField(null=True, blank=True) # 일산화탄소
    h2s         = models.FloatField(null=True, blank=True)
    co2         = models.FloatField(null=True, blank=True) # O2 18 ~ 25(25)
    o2          = models.FloatField(null=True, blank=True)
    no2         = models.FloatField(null=True, blank=True)
    so2         = models.FloatField(null=True, blank=True)
    o3          = models.FloatField(null=True, blank=True)
    nh3         = models.FloatField(null=True, blank=True)
    voc         = models.FloatField(null=True, blank=True)
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
