from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        "username",
        "email",
        "role",
        "department",
        "position",
        "is_active",
        "is_staff",
        "date_joined",
    ]
    list_filter = ["role", "is_active", "is_staff"]
    search_fields = ["username", "email", "department", "position"]
    ordering = ["-date_joined"]

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "디코나이 추가 정보",
            {
                "fields": ("role", "department", "position", "phone"),
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "추가 정보",
            {
                "fields": ("email", "role", "department", "position"),
            },
        ),
    )
