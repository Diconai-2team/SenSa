"""
0003_super_admin_and_lock — 백오피스 슈퍼관리자 채널 진입을 위한 v3 변경

추가:
  - role choices 에 'super_admin' 추가 (DB 측 영향은 없음, 검증/UI 차원)
  - is_locked BooleanField 추가
  - organization FK 추가 (backoffice.Organization)
  - position_obj FK 추가 (backoffice.Position)
"""
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_position'),
        # FK 대상 테이블이 미리 만들어져 있어야 함
        ('backoffice', '0001_initial'),
    ]

    operations = [
        # role choices 변경 (DB 영향 없음, ALTER 가 발생할 수 있어 명시)
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('operator', '운영자'),
                    ('admin', '관리자'),
                    ('super_admin', '슈퍼관리자'),
                ],
                default='operator',
                max_length=20,
                verbose_name='역할',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='is_locked',
            field=models.BooleanField(
                default=False,
                help_text='관리자 잠금 / 비밀번호 N회 실패 잠금. is_active 와 독립.',
                verbose_name='계정 잠금 여부',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='organization',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='users',
                to='backoffice.organization',
                verbose_name='소속 조직',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='position_obj',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='users',
                to='backoffice.position',
                verbose_name='직위',
            ),
        ),
        # legacy department/position 필드의 verbose_name help_text 갱신
        migrations.AlterField(
            model_name='user',
            name='department',
            field=models.CharField(
                blank=True, default='',
                help_text='legacy free-text. 새 백오피스는 organization FK 사용 권장',
                max_length=100,
                verbose_name='소속 부서',
            ),
        ),
        migrations.AlterField(
            model_name='user',
            name='position',
            field=models.CharField(
                blank=True, default='',
                help_text='legacy free-text. 새 백오피스는 position_obj FK 사용 권장',
                max_length=50,
                verbose_name='직급',
            ),
        ),
    ]
