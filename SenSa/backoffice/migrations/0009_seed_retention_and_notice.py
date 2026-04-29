"""
0009_seed_retention_and_notice — 보관 정책 5종 + 샘플 공지 3건
"""

from django.db import migrations
from django.utils import timezone
from datetime import timedelta


DEFAULT_RETENTION = [
    # (target, days, description)
    ("sensor_data", 30, "센서 1초당 1건 → 1개월 보존 후 삭제"),
    ("worker_location", 30, "작업자 위치 히스토리"),
    ("alarms", 365, "알람 이력 — 1년 보존 (감사 대비)"),
    ("notification_logs", 90, "알림 발송 결과"),
    ("audit_logs", 730, "감사 로그 — 2년 보존 (법정 요구)"),
]

SAMPLE_NOTICES = [
    {
        "title": "백오피스 시스템 오픈 안내",
        "category": "system",
        "content": "백오피스 시스템이 정식 오픈되었습니다.\n사용자/조직, 임계치, 알림 정책 등 운영 마스터를 모두 관리할 수 있습니다.",
        "is_pinned": True,
    },
    {
        "title": "4월 정기 안전 점검 일정 공지",
        "category": "maintenance",
        "content": "매월 마지막 주 금요일 오후 2시에 정기 안전 점검을 실시합니다.\n점검 시간 동안 일부 센서 데이터가 일시적으로 수신되지 않을 수 있습니다.",
        "is_pinned": False,
    },
    {
        "title": "밀폐공간 작업 시 안전 수칙 재공지",
        "category": "safety",
        "content": "밀폐공간 작업 진입 전 반드시:\n1. 산소 농도 18% 이상 확인\n2. 가스 측정기 휴대\n3. 외부 감시인 배치\n4. 비상 연락 체계 점검",
        "is_pinned": False,
    },
]


def seed(apps, schema_editor):
    DataRetentionPolicy = apps.get_model("backoffice", "DataRetentionPolicy")
    Notice = apps.get_model("backoffice", "Notice")

    for target, days, desc in DEFAULT_RETENTION:
        DataRetentionPolicy.objects.get_or_create(
            target=target,
            defaults={"retention_days": days, "description": desc},
        )

    now = timezone.now()
    for idx, n in enumerate(SAMPLE_NOTICES):
        Notice.objects.get_or_create(
            title=n["title"],
            defaults={
                "category": n["category"],
                "content": n["content"],
                "is_pinned": n["is_pinned"],
                "is_published": True,
                "published_from": now - timedelta(days=idx),
            },
        )


def unseed(apps, schema_editor):
    DataRetentionPolicy = apps.get_model("backoffice", "DataRetentionPolicy")
    Notice = apps.get_model("backoffice", "Notice")
    DataRetentionPolicy.objects.filter(
        target__in=[t[0] for t in DEFAULT_RETENTION]
    ).delete()
    Notice.objects.filter(title__in=[n["title"] for n in SAMPLE_NOTICES]).delete()


class Migration(migrations.Migration):
    dependencies = [("backoffice", "0008_retention_and_notice")]
    operations = [migrations.RunPython(seed, reverse_code=unseed)]
