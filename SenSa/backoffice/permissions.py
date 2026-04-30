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

# 데코레이터를 만들 때 원본 함수의 이름·docstring 등 메타데이터를 유지해 주는 유틸리티.

from django.contrib.auth.decorators import login_required

# 로그인 여부를 확인하는 Django 기본 데코레이터. 비로그인 사용자는 로그인 페이지로 리다이렉트.

from django.http import JsonResponse

# JSON 형식의 HTTP 응답을 만드는 Django 유틸리티. API 뷰에서 사용.

from django.shortcuts import render

# 템플릿을 렌더링해서 HttpResponse를 반환하는 단축 함수. 페이지 뷰에서 사용.


def _admin_can_access(user, menu_code: str) -> bool:
    """admin 역할 사용자가 특정 메뉴에 접근 가능한지 확인.
    MenuPermission 에 visible=True 등록되어 있어야 통과.
    """
    # admin 사용자가 특정 메뉴에 접근 권한이 있는지 DB에서 조회.
    if not menu_code:
        return (
            False  # menu_code가 명시되지 않으면 super_admin 전용으로 간주해 admin 차단.
        )
    from .models import MenuPermission

    return MenuPermission.objects.filter(
        role="admin", menu_code=menu_code, is_visible=True
    ).exists()
    # MenuPermission 테이블에서 admin 역할 + 해당 메뉴 + 조회 허용 여부 검색.
    # 레코드가 존재하면 True(통과), 없으면 False(차단).


def super_admin_required(menu_code: str = ""):
    """페이지 뷰 데코레이터 — 인자 있는 형태와 인자 없는 형태 둘 다 지원.

    Usage:
        @super_admin_required                    # super_admin only (legacy)
        @super_admin_required(menu_code='users') # super_admin + admin (메뉴 권한)
    """
    # 인자 없이 호출 — @super_admin_required (callable 이 바로 view 함수)
    if callable(menu_code):
        # 데코레이터 인자 없이 바로 함수에 붙인 경우: @super_admin_required
        # 이때 menu_code에 실제로 view 함수가 들어옴(Python 동작 방식).
        return _wrap_view(menu_code, "")

    # 인자 있는 호출 — @super_admin_required(menu_code='users')
    def decorator(view_func):
        return _wrap_view(view_func, menu_code)

    return decorator


def _wrap_view(view_func, menu_code: str):
    # HTML 페이지 뷰용 권한 래퍼 내부 구현.
    # 403 거절 시 JSON이 아닌 403.html 템플릿을 렌더링함.
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            # login_required 데코레이터가 막아주지만, 방어적으로 한 번 더 체크.
            return render(request, "backoffice/403.html", status=403)
        # super_admin 무조건 통과
        if user.is_super_admin_role:
            # 최고 관리자는 메뉴 권한 무관하게 모든 백오피스 페이지 접근 가능.
            return view_func(request, *args, **kwargs)
        # admin: menu_code 가 비어있으면 (landing 등) 무조건 통과,
        #        지정되어 있으면 MenuPermission 확인
        if user.role == "admin":
            if not menu_code or _admin_can_access(user, menu_code):
                # menu_code 없거나 MenuPermission에 허용 등록된 경우 통과.
                return view_func(request, *args, **kwargs)
        return render(request, "backoffice/403.html", status=403)
        # super_admin도 admin도 아니거나, admin인데 권한이 없으면 403 화면 반환.

    return _wrapped


def super_admin_required_api(menu_code: str = "", action: str = "read"):
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
        # 페이지 데코레이터와 같은 이유: 인자 없이 붙이면 menu_code에 view 함수가 들어옴.
        return _wrap_api_view(menu_code, "", "read")

    # 인자 있는 호출
    def decorator(view_func):
        return _wrap_api_view(view_func, menu_code, action)

    return decorator


def _wrap_api_view(view_func, menu_code: str, action: str):
    # JSON API 뷰용 권한 래퍼 내부 구현.
    # 거절 시 HTML 대신 JSON {'error': 'forbidden'} 형태로 응답함.
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({"error": "login_required"}, status=401)
            # 비로그인 사용자: 401 Unauthorized. 브라우저가 로그인 페이지로 유도할 수 있음.
        # super_admin 무조건 통과
        if user.is_super_admin_role:
            return view_func(request, *args, **kwargs)
        # admin 분기
        if user.role == "admin" and menu_code:
            from .models import MenuPermission

            perm = MenuPermission.objects.filter(
                role="admin", menu_code=menu_code
            ).first()
            # admin 역할의 해당 메뉴 권한 레코드 조회.
            if perm and perm.is_visible:
                if action == "read" or (action == "write" and perm.is_writable):
                    # 읽기 요청: is_visible만 있어도 통과.
                    # 쓰기 요청: is_visible + is_writable 둘 다 있어야 통과.
                    return view_func(request, *args, **kwargs)
        return JsonResponse({"error": "forbidden"}, status=403)
        # 조건을 만족하지 못하면 403 Forbidden JSON 응답.

    return _wrapped
