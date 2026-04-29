"""
0001_initial — backoffice 앱 신설 마이그레이션
  - Organization (회사+부서 self-FK 트리)
  - Position (직위 마스터)

데이터 시드는 별도 마이그레이션(0002_seed_defaults.py)에서 처리.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # accounts 의 v3 마이그레이션(super_admin role + is_locked + organization FK)이
        # backoffice 의 Organization/Position 테이블에 의존하므로
        # backoffice.0001 이 먼저 적용되어야 함.
        # accounts.0003 은 backoffice.0001 에 의존 (그쪽 dependencies 에 명시).
        ("accounts", "0002_user_position"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organization",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, verbose_name="조직명")),
                (
                    "code",
                    models.CharField(
                        blank=True, default="", max_length=50, verbose_name="부서 코드"
                    ),
                ),
                (
                    "description",
                    models.TextField(blank=True, default="", verbose_name="설명"),
                ),
                (
                    "is_unassigned_bucket",
                    models.BooleanField(
                        default=False, verbose_name="조직 없음 버킷 여부"
                    ),
                ),
                (
                    "sort_order",
                    models.IntegerField(default=100, verbose_name="정렬 순서"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.CASCADE,
                        related_name="children",
                        to="backoffice.organization",
                        verbose_name="상위 조직",
                    ),
                ),
                (
                    "leader",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="leading_organizations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="조직장",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="created_organizations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="updated_organizations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "조직",
                "verbose_name_plural": "조직 목록",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="organization",
            constraint=models.UniqueConstraint(
                fields=("parent", "name"), name="org_unique_name_per_parent"
            ),
        ),
        migrations.CreateModel(
            name="Position",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(max_length=50, unique=True, verbose_name="직위명"),
                ),
                (
                    "sort_order",
                    models.IntegerField(default=100, verbose_name="정렬 순서"),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="사용 여부"),
                ),
                (
                    "description",
                    models.TextField(blank=True, default="", verbose_name="설명"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="created_positions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="updated_positions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "직위",
                "verbose_name_plural": "직위 목록",
                "ordering": ["sort_order", "name"],
            },
        ),
    ]
