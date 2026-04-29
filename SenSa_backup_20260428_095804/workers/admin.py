"""
workers/admin.py — Django Admin 등록

/admin/workers/worker/            → 작업자 목록
/admin/workers/workerlocation/    → 위치 이력
/admin/workers/notificationlog/   → 알림 전송 이력 (Phase 4A)
"""

from django.contrib import admin
from .models import NotificationLog, Worker, WorkerLocation


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = [
        "worker_id",
        "name",
        "department",
        "position",
        "phone",
        "last_seen_at",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "department", "position"]
    search_fields = ["worker_id", "name", "email", "phone"]
    readonly_fields = ["created_at", "last_seen_at"]

    fieldsets = (
        (
            "기본 정보",
            {
                "fields": ("worker_id", "name", "department", "position", "is_active"),
            },
        ),
        (
            "연락처",
            {
                "fields": ("email", "phone"),
            },
        ),
        (
            "시스템",
            {
                "fields": ("last_seen_at", "created_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(WorkerLocation)
class WorkerLocationAdmin(admin.ModelAdmin):
    list_display = ["worker", "x", "y", "movement_status", "timestamp"]
    list_filter = ["movement_status", "worker"]
    readonly_fields = ["timestamp"]
    raw_id_fields = ["worker"]


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "sender",
        "send_type",
        "recipient_count",
        "message_preview",
        "sent_at",
    ]
    list_filter = ["send_type", "sent_at"]
    search_fields = ["message"]
    readonly_fields = ["sent_at"]
    filter_horizontal = ["recipients"]

    @admin.display(description="수신자 수")
    def recipient_count(self, obj):
        return obj.recipients.count()

    @admin.display(description="메시지")
    def message_preview(self, obj):
        return (obj.message[:40] + "…") if len(obj.message) > 40 else obj.message
