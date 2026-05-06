"""
backoffice/views/users.py — 사용자 관리.

라우팅:
  GET  /backoffice/users/                          → user_list (페이지)
  GET  /backoffice/api/users/<pk>/                 → user_detail_api
  POST /backoffice/api/users/create/               → user_create_api
  POST /backoffice/api/users/<pk>/update/          → user_update_api
  POST /backoffice/api/users/bulk-delete/          → user_bulk_delete_api
  POST /backoffice/api/users/bulk-lock/            → user_bulk_lock_api
  POST /backoffice/api/users/bulk-unlock/          → user_bulk_unlock_api
"""
from django.db.models import Q, Case, When, IntegerField, Value
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from accounts.models import User

from ..forms import UserCreateForm, UserUpdateForm
from ..models import Organization, Position
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


# ─── 페이지 ───

USER_PAGE_SIZE = 10

USER_SORT_OPTIONS = {
    'name_asc'      : ('first_name', '사용자명 오름차순'),
    'last_login_desc': ('-last_login', '최근 로그인순'),
    'created_desc'  : ('-date_joined', '등록일순'),
    'role_asc'      : ('role', '권한순'),
    'status_asc'    : (None, '계정 상태순'),  # is_active+is_locked 합성, 아래에서 처리
}


@super_admin_required(menu_code='users')
def user_list(request):
    """사용자 관리 — 목록 페이지 + 검색/필터/정렬/페이지네이션 (서버 렌더)."""
    qs = User.objects.select_related('organization', 'position_obj').all()

    # ── 검색 필터 ──
    q_name   = request.GET.get('name', '').strip()
    q_org    = request.GET.get('organization', '').strip()
    q_pos    = request.GET.get('position', '').strip()
    q_role   = request.GET.get('role', '').strip()
    q_status = request.GET.get('status', '').strip()

    if q_name:
        qs = qs.filter(
            Q(first_name__icontains=q_name) |
            Q(username__icontains=q_name)
        )
    if q_org:
        qs = qs.filter(organization_id=q_org)
    if q_pos:
        qs = qs.filter(position_obj_id=q_pos)
    if q_role:
        qs = qs.filter(role=q_role)
    if q_status == 'active':
        qs = qs.filter(is_active=True, is_locked=False)
    elif q_status == 'locked':
        qs = qs.filter(is_active=True, is_locked=True)
    elif q_status == 'disabled':
        qs = qs.filter(is_active=False)

    # ── 정렬 ──
    sort = request.GET.get('sort', 'name_asc')
    if sort == 'status_asc':
        # 사용(0) < 잠금(1) < 비활성(2) 순으로 정렬되도록 합성 키
        qs = qs.annotate(
            _status_key=Case(
                When(is_active=False, then=Value(2)),
                When(is_active=True, is_locked=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).order_by('_status_key', 'first_name')
    else:
        order_field = USER_SORT_OPTIONS.get(sort, USER_SORT_OPTIONS['name_asc'])[0]
        qs = qs.order_by(order_field, 'first_name')

    # ── 페이지네이션 ──
    total = qs.count()
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page = 1
    start = (page - 1) * USER_PAGE_SIZE
    rows = list(qs[start:start + USER_PAGE_SIZE])
    last_page = max(1, (total + USER_PAGE_SIZE - 1) // USER_PAGE_SIZE)

    ctx = {
        'rows'         : rows,
        'total'        : total,
        'page'         : page,
        'last_page'    : last_page,
        'page_size'    : USER_PAGE_SIZE,
        'page_start'   : start + 1 if total else 0,
        'page_end'     : min(start + USER_PAGE_SIZE, total),
        'page_range'   : range(1, last_page + 1),
        'sort'         : sort,
        'sort_options' : [(k, v[1]) for k, v in USER_SORT_OPTIONS.items()],
        'organizations': Organization.objects.filter(parent__isnull=False).order_by('sort_order'),
        'positions'    : Position.objects.filter(is_active=True),
        'roles'        : User.ROLE_CHOICES,
        'q': {
            'name': q_name, 'organization': q_org, 'position': q_pos,
            'role': q_role, 'status': q_status,
        },
    }
    return render(request, 'backoffice/users/list.html', ctx)


# ─── JSON API ───

def _user_to_dict(u: User) -> dict:
    return {
        'id'             : u.id,
        'name'           : u.first_name,
        'username'       : u.username,
        'organization_id': u.organization_id,
        'organization'   : u.display_organization,
        'position_obj_id': u.position_obj_id,
        'position'       : u.display_position,
        'role'           : u.role,
        'role_display'   : u.get_role_display(),
        'account_status' : u.account_status,
        'account_status_display': u.account_status_display,
        'email'          : u.email,
        'phone'          : u.phone,
        'last_login'     : u.last_login.strftime('%Y-%m-%d %H:%M:%S') if u.last_login else '-',
        'date_joined'    : u.date_joined.strftime('%Y-%m-%d') if u.date_joined else '-',
    }


@super_admin_required_api(menu_code='users', action='read')
@require_GET
def user_detail_api(request, pk):
    u = get_object_or_404(
        User.objects.select_related('organization', 'position_obj'),
        pk=pk,
    )
    return JsonResponse({'user': _user_to_dict(u)})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def user_create_api(request):
    form = UserCreateForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {'ok': False, 'errors': _form_errors_payload(form)},
            status=400,
        )
    u = form.save(created_by=request.user)
    return JsonResponse({'ok': True, 'user': _user_to_dict(u)})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def user_update_api(request, pk):
    u = get_object_or_404(User, pk=pk)
    form = UserUpdateForm(_parse_json(request), instance=u)
    if not form.is_valid():
        return JsonResponse(
            {'ok': False, 'errors': _form_errors_payload(form)},
            status=400,
        )
    u = form.save()
    return JsonResponse({'ok': True, 'user': _user_to_dict(u)})


@super_admin_required_api
@require_POST
def user_bulk_delete_api(request):
    """선택된 사용자 일괄 삭제. body: {"ids": [1, 2, 3]}"""
    ids = _parse_json(request).get('ids') or []
    if not isinstance(ids, list) or not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    # 자기 자신 삭제 방지
    if request.user.id in ids:
        return JsonResponse(
            {'ok': False, 'error': '본인 계정은 삭제할 수 없습니다.'},
            status=400,
        )
    deleted, _ = User.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


@super_admin_required_api
@require_POST
def user_bulk_lock_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    if request.user.id in ids:
        return JsonResponse(
            {'ok': False, 'error': '본인 계정은 잠글 수 없습니다.'},
            status=400,
        )
    n = User.objects.filter(id__in=ids, is_active=True).update(is_locked=True)
    return JsonResponse({'ok': True, 'locked': n})


@super_admin_required_api
@require_POST
def user_bulk_unlock_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = User.objects.filter(id__in=ids).update(is_locked=False)
    return JsonResponse({'ok': True, 'unlocked': n})
