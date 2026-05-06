"""
backoffice/permissions.py — 백오피스 진입 권한 게이트

[v5 변경]
  v1: super_admin 만 백오피스 전체 접근. admin/operator → 403.
  v5: super_admin → 전체 접근 (변경 없음).
      admin       → MenuPermission(role='admin', is_visible=True) 인 메뉴만 접근.
      operator    → 백오피스 진입 자체 불가.

  '메뉴 코드' 는 super_admin_required(menu_code='users') 식으로 데코레이터에 명시.
  명시 안 하면 super_admin 만 접근 가능 (안전 default).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render


def _admin_can_access(user, menu_code: str) -> bool:
    """admin 역할 사용자가 특정 메뉴에 접근 가능한지 확인.
    MenuPermission 에 visible=True 등록되어 있어야 통과.
    """
    if not menu_code:
        return False  # 명시 없으면 super_admin only
    from .models import MenuPermission
    return MenuPermission.objects.filter(
        role='admin', menu_code=menu_code, is_visible=True
    ).exists()


def super_admin_required(menu_code: str = ''):
    """페이지 뷰 데코레이터 — 인자 있는 형태와 인자 없는 형태 둘 다 지원.

    Usage:
        @super_admin_required                    # super_admin only (legacy)
        @super_admin_required(menu_code='users') # super_admin + admin (메뉴 권한)
    """
    # 인자 없이 호출 — @super_admin_required (callable 이 바로 view 함수)
    if callable(menu_code):
        return _wrap_view(menu_code, '')

    # 인자 있는 호출 — @super_admin_required(menu_code='users')
    def decorator(view_func):
        return _wrap_view(view_func, menu_code)
    return decorator


def _wrap_view(view_func, menu_code: str):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return render(request, 'backoffice/403.html', status=403)
        # super_admin 무조건 통과
        if user.is_super_admin_role:
            return view_func(request, *args, **kwargs)
        # admin: menu_code 가 비어있으면 (landing 등) 무조건 통과,
        #        지정되어 있으면 MenuPermission 확인
        if user.role == 'admin':
            if not menu_code or _admin_can_access(user, menu_code):
                return view_func(request, *args, **kwargs)
        return render(request, 'backoffice/403.html', status=403)
    return _wrapped


def super_admin_required_api(menu_code: str = '', action: str = 'read'):
    """JSON API 뷰 데코레이터.

    [v6 변경] 인자 없는 형태와 인자 있는 형태 둘 다 지원.

    Usage:
        @super_admin_required_api                                    # super_admin only (legacy)
        @super_admin_required_api(menu_code='users', action='read')  # admin 도 통과
        @super_admin_required_api(menu_code='users', action='write') # admin 통과 + is_writable 필요

    action='read'  → MenuPermission.is_visible 만 확인
    action='write' → MenuPermission.is_visible AND is_writable 둘 다 필요
    """
    # 인자 없이 호출 — @super_admin_required_api (callable 이 바로 view 함수)
    if callable(menu_code):
        return _wrap_api_view(menu_code, '', 'read')

    # 인자 있는 호출
    def decorator(view_func):
        return _wrap_api_view(view_func, menu_code, action)
    return decorator


def _wrap_api_view(view_func, menu_code: str, action: str):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({'error': 'login_required'}, status=401)
        # super_admin 무조건 통과
        if user.is_super_admin_role:
            return view_func(request, *args, **kwargs)
        # admin 분기
        if user.role == 'admin' and menu_code:
            from .models import MenuPermission
            perm = MenuPermission.objects.filter(role='admin', menu_code=menu_code).first()
            if perm and perm.is_visible:
                if action == 'read' or (action == 'write' and perm.is_writable):
                    return view_func(request, *args, **kwargs)
        return JsonResponse({'error': 'forbidden'}, status=403)
    return _wrapped
