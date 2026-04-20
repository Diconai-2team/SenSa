from django.contrib import admin
from .models import MapImage


@admin.register(MapImage)
class MapImageAdmin(admin.ModelAdmin):
    list_display = ['name', 'width', 'height', 'is_active', 'uploaded_at']
    list_filter = ['is_active']
