from django.contrib import admin
from .models import GeoFence


@admin.register(GeoFence)
class GeoFenceAdmin(admin.ModelAdmin):
    list_display = ['name', 'zone_type', 'risk_level', 'is_active', 'created_at']
    list_filter = ['zone_type', 'risk_level', 'is_active']
    search_fields = ['name']
