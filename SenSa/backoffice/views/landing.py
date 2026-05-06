"""
backoffice/views/landing.py — 백오피스 메인 진입 화면.

라우팅: GET /backoffice/  → views.landing
"""
from django.shortcuts import render

from accounts.models import User

from ..models import Organization, Position
from ..permissions import super_admin_required


@super_admin_required
def landing(request):
    """백오피스 메인 진입 화면.
    super_admin 은 무제한, admin 도 진입 가능 (개별 메뉴는 MenuPermission 으로 제어).
    """
    # admin 도 통과시키기 위해 super_admin_required 안에서 막힌 admin 을 다시 허용
    # → 데코레이터 인자 없이 호출되면 super_admin only 라서, landing 은 view 자체에서 분기
    if not (request.user.is_super_admin_role or request.user.role == 'admin'):
        from django.shortcuts import render as _r
        return _r(request, 'backoffice/403.html', status=403)

    ctx = {
        'stats': {
            'user_count'    : User.objects.count(),
            'org_count'     : Organization.objects.exclude(
                is_unassigned_bucket=True
            ).count(),
            'position_count': Position.objects.filter(is_active=True).count(),
            'locked_count'  : User.objects.filter(is_locked=True).count(),
        },
    }
    return render(request, 'backoffice/landing.html', ctx)
