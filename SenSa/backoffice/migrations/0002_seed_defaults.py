"""
0002_seed_defaults — 기본 마스터 데이터 시드

조직 트리: (주)가람이앤지 회사 1개 + 13개 부서 (피그마 명세) + '조직 없음' 버킷
직위:      대표이사 / 이사 / 부장 / 차장 / 과장 / 대리 / 사원 (sort_order 1~7)

idempotent — 이미 존재하면 skip. 운영 DB 에 사용자가 만든 조직/직위 보존.
"""

from django.db import migrations


COMPANY_NAME = "(주)가람이앤지"

DEFAULT_DEPARTMENTS = [
    "경영지원팀",
    "영업팀",
    "사업기획팀",
    "기술연구소",
    "개발팀",
    "관제운영팀",
    "시스템운영팀",
    "안전관리팀",
    "품질관리팀",
    "생산관리팀",
    "설치공사팀",
    "유지보수팀",
    "고객지원팀",
]

DEFAULT_POSITIONS = [
    # (name, sort_order)
    ("대표이사", 1),
    ("이사", 2),
    ("부장", 3),
    ("차장", 4),
    ("과장", 5),
    ("대리", 6),
    ("사원", 7),
]


def seed(apps, schema_editor):
    Organization = apps.get_model("backoffice", "Organization")
    Position = apps.get_model("backoffice", "Position")

    # ── 회사 (root) ──
    company, _ = Organization.objects.get_or_create(
        parent=None,
        name=COMPANY_NAME,
        defaults={"sort_order": 0},
    )

    # ── 부서 (회사 하위) ──
    for idx, dept_name in enumerate(DEFAULT_DEPARTMENTS, start=1):
        Organization.objects.get_or_create(
            parent=company,
            name=dept_name,
            defaults={
                "code": f"{idx:03d}",
                "sort_order": idx * 10,
            },
        )

    # ── '조직 없음' 가상 부서 ──
    Organization.objects.get_or_create(
        parent=company,
        name="조직 없음",
        defaults={
            "is_unassigned_bucket": True,
            "sort_order": 9999,
            "description": "소속 부서가 지정되지 않은 사용자가 자동으로 들어가는 가상 부서",
        },
    )

    # ── 직위 ──
    for name, sort_order in DEFAULT_POSITIONS:
        Position.objects.get_or_create(
            name=name,
            defaults={"sort_order": sort_order, "is_active": True},
        )


def unseed(apps, schema_editor):
    """롤백 — 시드한 데이터만 제거. 사용자가 추가한 건 손대지 않음."""
    Organization = apps.get_model("backoffice", "Organization")
    Position = apps.get_model("backoffice", "Position")

    Organization.objects.filter(
        name__in=DEFAULT_DEPARTMENTS + ["조직 없음", COMPANY_NAME],
    ).delete()
    Position.objects.filter(
        name__in=[p[0] for p in DEFAULT_POSITIONS],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("backoffice", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]
