from django.db import models

ALARM_TYPE_CHOICES = [
    # 위험구역 / 복합
    ('geofence_enter',        '위험구역 진입'),
    ('combined',              '복합 위험'),          # reserved (미사용)
    # 센서 알람
    ('sensor_caution',        '센서 주의'),          # 최초 주의 진입
    ('sensor_danger',         '센서 위험'),          # 최초 위험 진입 / 악화
    ('sensor_ongoing',        '센서 지속 중'),       # 지속 상태 재알림 (ongoing)
    ('sensor_recover_partial','센서 부분 회복'),
    ('sensor_recover_normal', '센서 정상 회복'),
    # 작업자 상태 알람 (worker_evaluator)
    ('state_caution_enter',   '작업자 주의'),
    ('state_danger_enter',    '작업자 위험'),
    ('state_escalate',        '상태 에스컬레이션'),
    ('state_ongoing',         '상태 지속 중'),
    ('state_recover_partial', '부분 회복'),
    ('state_recover_safe',    '완전 회복'),
    # AI 탐지 알람 (ml_engine)
    ('ai_prediction',         'AI 예측'),            # reserved (기존 호환)
    ('ai_anomaly_warning',    'AI 통계 이상'),
    ('ai_trend_shift',        'AI 급변 탐지'),
    ('ai_ml_anomaly',         'AI ML 이상'),
    ('ai_predictive_warning', 'AI 예측 주의'),
    ('ai_predictive_alert',   'AI 예측 위험'),
    ('ai_drift_alert',        'AI 드리프트 탐지'),
    ('ai_correlation',        'AI 상관관계 이상'),
]

ALARM_LEVEL_CHOICES = [
    ('info',     '정보'),
    ('caution',  '주의'),
    ('danger',   '위험'),
    ('critical', '심각'),
]


class Alarm(models.Model):
    """알람 기록. is_ai=True 이면 ml_engine AI 파이프라인이 생성한 알람."""
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
    device_id         = models.CharField(max_length=50, blank=True, default='')
    related_device_id = models.CharField(max_length=50, blank=True, default='')
    sensor_type       = models.CharField(max_length=20, blank=True, default='')
    message     = models.TextField()
    is_read     = models.BooleanField(default=False)
    is_ai       = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'],                              name='alarm_created_idx'),
            models.Index(fields=['alarm_type', '-created_at'],                name='alarm_type_created_idx'),
            models.Index(fields=['device_id', 'alarm_type', 'created_at'],    name='alarm_device_type_created_idx'),
            models.Index(fields=['is_read', '-created_at'],                   name='alarm_read_created_idx'),
        ]

    def __str__(self):
        ai_tag = ' [AI]' if self.is_ai else ''
        return f"[{self.alarm_level}]{ai_tag} {self.message[:40]}"


class AIPrediction(models.Model):
    """
    ARIMA 예측 알람 기록 (ai_predictive_alert / ai_predictive_warning).

    ARIMA가 미래 임계치 초과를 예측할 때 생성 → 이후 실제 데이터로 성공/실패 검증.
    slope / if_score 필드는 예측 시점의 IsolationForest 컨텍스트 정보.

    result:
      'pending' — 아직 검증 안 됨 (기본값)
      'success' — 예측 후 실제로 임계치 도달
      'failure' — expires_at 내 임계치 미도달
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
