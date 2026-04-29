from django.contrib import admin

from .models import VRTrainingLog


@admin.register(VRTrainingLog)
class VRTrainingLogAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "check_date",
        "progress_display",
        "is_completed",
        "completed_at",
    )
    list_filter = ("is_completed", "check_date")
    search_fields = ("user__username",)
    readonly_fields = ("started_at", "updated_at", "completed_at")
    ordering = ("-check_date", "-updated_at")

    @admin.display(description="진행률")
    def progress_display(self, obj):
        return f"{obj.progress_percent}% ({obj.last_position_sec}/{obj.total_duration_sec}s)"
