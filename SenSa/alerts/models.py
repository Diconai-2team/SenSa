from django.db import models


ALARM_TYPE_CHOICES = [
    ('geofence_enter',        '위험구역 진입'),
    ('sensor_caution',        '센서 주의'),
    ('sensor_danger',         '센서 위험'),
    ('combined',              '복합 위험'),
    # AI 탐지 알람 (ml_engine)
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

    # 운영자 피드백 (AI 알람 전용)
    FEEDBACK_CHOICES = [('tp', '정탐'), ('fp', '오탐')]
    feedback    = models.CharField(max_length=2, choices=FEEDBACK_CHOICES, null=True, blank=True)
    feedback_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # 시간 범위 필터 (대부분의 쿼리 공통)
            models.Index(fields=['-created_at'], name='alarm_created_idx'),
            # alarm_type + 시간 — type별 현황, evaluator ML 집계
            models.Index(fields=['alarm_type', '-created_at'], name='alarm_type_created_idx'),
            # device_id + alarm_type + 시간 — EXISTS 서브쿼리, 중복 억제
            models.Index(fields=['device_id', 'alarm_type', 'created_at'], name='alarm_device_type_created_idx'),
            # 읽음 여부 필터
            models.Index(fields=['is_read', '-created_at'], name='alarm_read_created_idx'),
        ]

    def __str__(self):
        return f"[{self.alarm_level}] {self.message[:40]}"
