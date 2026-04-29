from django.contrib import admin
from .models import Device, SensorData


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = [
        "device_id",
        "device_name",
        "sensor_type",
        "x",
        "y",
        "status",
        "is_active",
    ]
    list_filter = ["sensor_type", "status", "is_active"]
    search_fields = ["device_id", "device_name"]


@admin.register(SensorData)
class SensorDataAdmin(admin.ModelAdmin):
    list_display = ["device", "co", "h2s", "co2", "status", "timestamp"]
    list_filter = ["status"]
    date_hierarchy = "timestamp"
