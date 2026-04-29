"""
backoffice/context_processors.py — 모든 백오피스 템플릿에 권한 정보 주입.

base.html SNB 가 이 데이터를 보고 admin 사용자에겐 권한 있는 메뉴만 표시.
"""

ALL_MENU_CODES = (
    "users",
    "menus",
    "devices",
    "maps",
    "references",
    "operations",
    "notices",
    "notifications",
)


def menu_perms(request):
    """current user 의 SNB 표시 가능 메뉴 + writable 메뉴 set."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"visible_menus": set(), "writable_menus": set()}

    # super_admin → 전부 visible + writable
    if getattr(user, "is_super_admin_role", False):
        full = set(ALL_MENU_CODES)
        return {"visible_menus": full, "writable_menus": full}

    if user.role == "admin":
        from .models import MenuPermission

        perms = MenuPermission.objects.filter(role="admin")
        visible = {p.menu_code for p in perms if p.is_visible}
        writable = {p.menu_code for p in perms if p.is_visible and p.is_writable}
        return {"visible_menus": visible, "writable_menus": writable}

    return {"visible_menus": set(), "writable_menus": set()}
