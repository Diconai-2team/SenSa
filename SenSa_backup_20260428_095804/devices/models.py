"""
devices/models.py — 센서 장비 + 측정값 히스토리

[변경 이력]
  Phase A: 초기 4종 가스 필드 (co, h2s, co2, o2) + temperature
  Gas 병합: Device.geofence FK + 9종 가스 필드 (no2, so2, o3, nh3, voc)
  Power 병합 (본 커밋): SensorData 에 전력 3필드 (current, voltage, watt)
    → 동적 전력 판정(최근 24시간 중앙값 기반)의 데이터 소스.
    → alerts.services._get_24h_avg_watt 가 이 watt 필드를 읽음.
"""

from django.db import models


SENSOR_TYPE_CHOICES = [
    ("gas", "가스"),
    ("power", "전력"),
    ("temperature", "온도"),
    ("motion", "동작"),
]

STATUS_CHOICES = [
    ("normal", "정상"),
    ("caution", "주의"),
    ("danger", "위험"),
]


class Device(models.Model):
    """센서 디바이스 — x, y는 이미지 내부 좌표"""

    device_id = models.CharField(max_length=50, unique=True)
    device_name = models.CharField(max_length=100)
    sensor_type = models.CharField(
        max_length=20, choices=SENSOR_TYPE_CHOICES, default="gas"
    )
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="normal")
    last_value = models.FloatField(null=True, blank=True)
    last_value_unit = models.CharField(max_length=20, blank=True, default="")
    is_active = models.BooleanField(default=True)

    # ── 소속 지오펜스 (Gas 병합) ──
    # null=True             → 바깥 공용 구역 센서도 허용
    # on_delete=SET_NULL    → 지오펜스 삭제해도 센서는 남음
    # related_name='devices'→ geofence.devices.all() 로 역참조 가능
    geofence = models.ForeignKey(
        "geofence.GeoFence",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="devices",
        help_text="이 센서가 속한 지오펜스 (없으면 공용 구역)",
    )

    class Meta:
        ordering = ["device_id"]

    def __str__(self):
        return f"{self.device_name} ({self.device_id})"


class SensorData(models.Model):
    """
    센서 측정값 히스토리 — 9종 가스 + 전력 3필드 + 온도

    가스 9종 (Gas 전담 팀원 정의):
      co, h2s, co2, o2, no2, so2, o3, nh3, voc

    전력 3종 (Power 병합):
      current — 전류 (A)
      voltage — 전압 (V)
      watt    — 전력 (W)
      → classify_power 의 24시간 중앙값 동적 임계치 계산의 원천 데이터
    """

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="data")

    # ─── 가스 9종 ───
    co = models.FloatField(null=True, blank=True, help_text="일산화탄소 (ppm)")
    h2s = models.FloatField(null=True, blank=True, help_text="황화수소 (ppm)")
    co2 = models.FloatField(null=True, blank=True, help_text="이산화탄소 (ppm)")
    o2 = models.FloatField(null=True, blank=True, help_text="산소 (%), 구간형 판정")
    no2 = models.FloatField(null=True, blank=True, help_text="이산화질소 (ppm)")
    so2 = models.FloatField(null=True, blank=True, help_text="이산화황 (ppm)")
    o3 = models.FloatField(null=True, blank=True, help_text="오존 (ppm)")
    nh3 = models.FloatField(null=True, blank=True, help_text="암모니아 (ppm)")
    voc = models.FloatField(null=True, blank=True, help_text="유기화합물 (ppm)")

    # ─── 전력 3종 (Power 병합) ───
    current = models.FloatField(null=True, blank=True, help_text="전류 (A)")
    voltage = models.FloatField(null=True, blank=True, help_text="전압 (V)")
    watt = models.FloatField(null=True, blank=True, help_text="전력 (W)")

    # ─── 기타 ───
    temperature = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="normal")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["device", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.device.device_name} @ {self.timestamp}"
