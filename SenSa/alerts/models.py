from django.db import models


ALARM_TYPE_CHOICES = [
    # 지오펜스 이벤트 (1회성)
    ('zone_enter',           '구역 진입'),
    ('zone_exit',            '구역 이탈'),
    # 작업자 상태 전이
    ('state_caution_enter',  '주의 진입'),
    ('state_danger_enter',   '위험 진입'),
    ('state_escalate',       '상태 악화'),
    ('state_recover_partial','부분 회복'),
    ('state_recover_safe',   '안전 복귀'),
    ('state_ongoing',        '상태 지속'),
    # 센서 상태 전이
    ('sensor_caution',       '센서 주의'),
    ('sensor_danger',        '센서 위험'),
    ('sensor_recover_partial','센서 부분 회복'),
    ('sensor_recover_normal', '센서 정상 복귀'),
]

ALARM_LEVEL_CHOICES = [
    ('info',     '정보'),
    ('caution',  '주의'),
    ('danger',   '위험'),
    ('critical', '심각'),
]


class Alarm(models.Model):
    """
    알람 기록
    - 작업자가 지오펜스에 진입했거나
    - 센서가 임계치를 초과했거나
    - 두 조건이 동시에 발생했을 때 생성
    """
    alarm_type  = models.CharField(max_length=30, choices=ALARM_TYPE_CHOICES)
    alarm_level = models.CharField(max_length=20, choices=ALARM_LEVEL_CHOICES, default='caution')

    # 관련 작업자 정보
    worker_id   = models.CharField(max_length=50, blank=True, default='')
    worker_name = models.CharField(max_length=100, blank=True, default='')
    worker_x    = models.FloatField(null=True, blank=True)
    worker_y    = models.FloatField(null=True, blank=True)

    # 관련 지오펜스 (다른 앱의 모델을 문자열로 참조)
    geofence    = models.ForeignKey(
        'geofence.GeoFence', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='alarms'
    )

    # 관련 센서
    device_id   = models.CharField(max_length=50, blank=True, default='')
    sensor_type = models.CharField(max_length=20, blank=True, default='')

    # 알람 메시지
    message     = models.TextField()

    # 읽음 여부
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.alarm_level}] {self.message[:40]}"
