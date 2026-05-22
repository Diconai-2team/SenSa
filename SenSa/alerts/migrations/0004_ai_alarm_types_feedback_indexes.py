from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alerts", "0003_alter_alarm_alarm_type_aiprediction"),
    ]

    operations = [
        # 1. alarm_type choices 확장 (ml_engine AI 타입 추가)
        migrations.AlterField(
            model_name="alarm",
            name="alarm_type",
            field=models.CharField(
                choices=[
                    ("geofence_enter",        "위험구역 진입"),
                    ("sensor_caution",        "센서 주의"),
                    ("sensor_danger",         "센서 위험"),
                    ("combined",              "복합 위험"),
                    ("ai_prediction",         "AI 예측"),
                    ("ai_anomaly_warning",    "AI 통계 이상"),
                    ("ai_trend_shift",        "AI 급변 탐지"),
                    ("ai_ml_anomaly",         "AI ML 이상"),
                    ("ai_predictive_warning", "AI 예측 주의"),
                    ("ai_predictive_alert",   "AI 예측 위험"),
                    ("ai_drift_alert",        "AI 드리프트 탐지"),
                    ("ai_correlation",        "AI 상관관계 이상"),
                ],
                max_length=30,
            ),
        ),
        # 2. 운영자 피드백 필드 추가
        migrations.AddField(
            model_name="alarm",
            name="feedback",
            field=models.CharField(
                blank=True,
                choices=[("tp", "정탐"), ("fp", "오탐")],
                max_length=2,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="alarm",
            name="feedback_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # 3. 쿼리 성능 인덱스
        migrations.AddIndex(
            model_name="alarm",
            index=models.Index(fields=["-created_at"], name="alarm_created_idx"),
        ),
        migrations.AddIndex(
            model_name="alarm",
            index=models.Index(fields=["alarm_type", "-created_at"], name="alarm_type_created_idx"),
        ),
        migrations.AddIndex(
            model_name="alarm",
            index=models.Index(fields=["device_id", "alarm_type", "created_at"], name="alarm_device_type_created_idx"),
        ),
        migrations.AddIndex(
            model_name="alarm",
            index=models.Index(fields=["is_read", "-created_at"], name="alarm_read_created_idx"),
        ),
    ]
