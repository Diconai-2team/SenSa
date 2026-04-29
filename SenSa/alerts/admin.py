from django.contrib import admin
from .models import Alarm


@admin.register(Alarm)
class AlarmAdmin(admin.ModelAdmin):
    list_display = [
        "alarm_type",
        "alarm_level",
        "worker_name",
        "device_id",
        "geofence",
        "is_read",
        "created_at",
    ]
    list_filter = ["alarm_type", "alarm_level", "is_read"]
    search_fields = ["message", "worker_name", "device_id"]
    date_hierarchy = "created_at"
