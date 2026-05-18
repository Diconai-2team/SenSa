from django.contrib import admin
from .models import GeoFence, ZoneEvent


@admin.register(GeoFence)
class GeoFenceAdmin(admin.ModelAdmin):
    list_display = ['name', 'zone_type', 'risk_level', 'is_active', 'created_at']
    list_filter = ['zone_type', 'risk_level', 'is_active', 'is_dynamic', 'tier']
    search_fields = ['name', 'source_device__device_id']


@admin.register(ZoneEvent)
class ZoneEventAdmin(admin.ModelAdmin):
    list_display = ['zone', 'event_type', 'from_tier', 'to_tier', 'trigger_source', 'created_at']
    list_filter = ['event_type', 'trigger_source']
    search_fields = ['zone__name']
    raw_id_fields = ['zone']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
