from django.contrib import admin

from .models import SafetyChecklist


@admin.register(SafetyChecklist)
class SafetyChecklistAdmin(admin.ModelAdmin):
    list_display = ('user', 'check_date', 'checked_count', 'completed_at')
    list_filter = ('check_date',)
    search_fields = ('user__username',)
    readonly_fields = ('completed_at', 'updated_at')
    ordering = ('-check_date', '-completed_at')

    @admin.display(description='체크 항목 수')
    def checked_count(self, obj):
        return len(obj.checked_items or [])