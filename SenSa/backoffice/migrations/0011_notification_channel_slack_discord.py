"""
Migration 0011: NotificationLog channel choices에 slack/discord 추가.

외부 webhook 알림(Slack/Discord) 발송 이력을 NotificationLog에 기록하기 위해
channel 필드의 choices에 'slack', 'discord' 추가.

choices 변경은 DB 스키마 변경 없음 (CharField 길이 이내) → migrations.AlterField 만 필요.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backoffice', '0010_audit_and_device_history'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationlog',
            name='channel',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('app',      '앱 푸시'),
                    ('realtime', '관제 실시간'),
                    ('sms',      'SMS'),
                    ('email',    '이메일'),
                    ('slack',    'Slack Webhook'),
                    ('discord',  'Discord Webhook'),
                ],
            ),
        ),
    ]
