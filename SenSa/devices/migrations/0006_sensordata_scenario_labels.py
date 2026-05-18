# Generated for C′-3a (5차 세션) — SensorData 라벨 컬럼 추가
# 적용 후 fastapi_generator 가 scenario_id / expected_phase / expected_status 동봉 가능

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0005_sensordata_current_sensordata_voltage_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='sensordata',
            name='scenario_id',
            field=models.CharField(
                blank=True, db_index=True,
                help_text='시나리오 매핑 또는 레거시 모드명 (G3, P1, legacy:normal 등)',
                max_length=20, null=True,
            ),
        ),
        migrations.AddField(
            model_name='sensordata',
            name='expected_phase',
            field=models.IntegerField(
                blank=True,
                help_text='6-phase 라벨 (0~5). 레거시 모드는 null',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='sensordata',
            name='expected_status',
            field=models.CharField(
                blank=True,
                help_text='정답 라벨: normal | caution | danger. 레거시 모드는 null',
                max_length=10, null=True,
            ),
        ),
    ]
