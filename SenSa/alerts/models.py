from django.db import models

ALARM_TYPE_CHOICES = [
    ('geofence_enter', '위험구역 진입'),
    ('sensor_caution', '센서 주의'),
    ('sensor_danger',  '센서 위험'),
    ('combined',       '복합 위험'),
    ('ai_prediction',  'AI 예측'),
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
    [ARIMA 연동]
      is_ai=True : ARIMA 패턴 이탈 탐지로 격상된 알람
    """
    alarm_type  = models.CharField(max_length=30, choices=ALARM_TYPE_CHOICES)
    alarm_level = models.CharField(max_length=20, choices=ALARM_LEVEL_CHOICES, default='caution')
    worker_id   = models.CharField(max_length=50, blank=True, default='')
    worker_name = models.CharField(max_length=100, blank=True, default='')
    worker_x    = models.FloatField(null=True, blank=True)
    worker_y    = models.FloatField(null=True, blank=True)
    geofence    = models.ForeignKey(
        'geofence.GeoFence', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='alarms'
    )
    device_id   = models.CharField(max_length=50, blank=True, default='')
    sensor_type = models.CharField(max_length=20, blank=True, default='')
    message     = models.TextField()
    is_read     = models.BooleanField(default=False)
    is_ai       = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        ai_tag = ' [AI]' if self.is_ai else ''
        return f"[{self.alarm_level}]{ai_tag} {self.message[:40]}"


class AIPrediction(models.Model):
    """
    IsolationForest 기반 AI 예측 기록.

    예측 발생 시 생성 → 이후 실제 데이터로 성공/실패 검증.

    result:
      'pending' — 아직 검증 안 됨 (기본값)
      'success' — 예측 후 실제로 임계치 초과
      'failure' — 예측 후 임계치 미도달
    """
    RESULT_CHOICES = [
        ('pending', '검증 중'),
        ('success', '예측 성공'),
        ('failure', '예측 실패'),
    ]

    device_id       = models.CharField(max_length=50)
    sensor_key      = models.CharField(max_length=20)  # 예: 'co', 'watt'
    sensor_type     = models.CharField(max_length=20)  # 예: 'gas', 'power'

    # 예측 시점 값
    value_at_predict = models.FloatField()
    threshold        = models.FloatField()
    slope            = models.FloatField()
    if_score         = models.FloatField()

    # 예측 내용
    predicted_ticks  = models.IntegerField()   # 몇 틱 후 초과 예상
    predicted_value  = models.FloatField()     # 예상 도달값

    # 검증
    result           = models.CharField(max_length=10, choices=RESULT_CHOICES, default='pending')
    expires_at       = models.DateTimeField()  # 예측 마감 시각
    created_at       = models.DateTimeField(auto_now_add=True)

    # 연결된 알람
    alarm            = models.OneToOneField(
        Alarm, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='ai_prediction'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['device_id', 'sensor_key', 'result']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"[{self.result}] {self.device_id}/{self.sensor_key} → {self.predicted_value}"
