"""
backoffice/views/organizations.py — 조직 관리 (회사/부서 트리).

라우팅:
  GET  /backoffice/organizations/                          → organization_manage (페이지)
  GET  /backoffice/api/organizations/<pk>/                 → organization_detail_api
  POST /backoffice/api/organizations/create/               → organization_create_api
  POST /backoffice/api/organizations/<pk>/update/          → organization_update_api
  POST /backoffice/api/organizations/<pk>/delete/          → organization_delete_api
  POST /backoffice/api/organizations/<pk>/assign/          → organization_assign_members_api
  POST /backoffice/api/organizations/<pk>/remove/          → organization_remove_members_api
  POST /backoffice/api/organizations/<pk>/set-leader/      → organization_set_leader_api
  GET  /backoffice/api/organizations/member-picker/        → organization_member_picker_api
"""
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from accounts.models import User

from ..forms import OrganizationForm
from ..models import Organization
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


@super_admin_required(menu_code='users')
def organization_manage(request):
    """조직 관리 메인 페이지.
    초기 진입 시 회사(root) 가 펼쳐진 상태. 부서 선택 → 우측 상세는 AJAX.
    """
    company = Organization.objects.filter(parent__isnull=True).first()
    departments = []
    if company:
        departments = list(
            company.children.exclude(is_unassigned_bucket=True).order_by('sort_order')
        )
        unassigned = company.children.filter(is_unassigned_bucket=True).first()
        if unassigned:
            departments.append(unassigned)

    ctx = {
        'company'    : company,
        'departments': departments,
    }
    return render(request, 'backoffice/organizations/manage.html', ctx)


def _org_to_dict(org: Organization) -> dict:
    return {
        'id'          : org.id,
        'name'        : org.name,
        'code'        : org.code,
        'parent_id'   : org.parent_id,
        'description' : org.description,
        'leader_id'   : org.leader_id,
        'leader_name' : org.leader.first_name if org.leader else None,
        'is_unassigned_bucket': org.is_unassigned_bucket,
        'is_root'     : org.is_root,
        'member_count': org.member_count,
        'updated_at'  : org.updated_at.strftime('%Y-%m-%d %H:%M') if org.updated_at else '-',
        'updated_by_name': org.updated_by.first_name if org.updated_by else '-',
    }


@super_admin_required_api
@require_GET
def organization_detail_api(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    members = org.users.select_related('position_obj').order_by('-id')
    members_data = [{
        'id'      : u.id,
        'name'    : u.first_name,
        'username': u.username,
        'position': u.display_position,
        'account_status'        : u.account_status,
        'account_status_display': u.account_status_display,
        'is_leader': (u.id == org.leader_id),
    } for u in members]

    return JsonResponse({
        'organization': _org_to_dict(org),
        'members'     : members_data,
    })


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def organization_create_api(request):
    form = OrganizationForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {'ok': False, 'errors': _form_errors_payload(form)},
            status=400,
        )
    org = form.save(by=request.user)
    return JsonResponse({'ok': True, 'organization': _org_to_dict(org)})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def organization_update_api(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    if org.is_unassigned_bucket:
        return JsonResponse(
            {'ok': False, 'error': '"조직 없음" 가상 부서는 수정할 수 없습니다.'},
            status=400,
        )
    form = OrganizationForm(_parse_json(request), instance=org)
    if not form.is_valid():
        return JsonResponse(
            {'ok': False, 'errors': _form_errors_payload(form)},
            status=400,
        )
    org = form.save(by=request.user)
    return JsonResponse({'ok': True, 'organization': _org_to_dict(org)})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def organization_delete_api(request, pk):
    """부서 삭제. 소속 사용자는 '조직 없음' 으로 자동 이동."""
    org = get_object_or_404(Organization, pk=pk)
    if org.is_unassigned_bucket:
        return JsonResponse(
            {'ok': False, 'error': '"조직 없음" 가상 부서는 삭제할 수 없습니다.'},
            status=400,
        )
    if org.is_root:
        return JsonResponse(
            {'ok': False, 'error': '회사(루트) 노드는 삭제할 수 없습니다.'},
            status=400,
        )
    # 소속 사용자 → 조직 없음 으로 이동
    company = org.parent
    bucket = company.children.filter(is_unassigned_bucket=True).first() if company else None
    if bucket:
        org.users.update(organization=bucket)

    org.delete()
    return JsonResponse({'ok': True})


@super_admin_required_api
@require_POST
def organization_assign_members_api(request, pk):
    """피그마 '구성원 추가' — 다른 부서 사용자를 이 부서로 옮김(또는 겸직).
    body: {"user_ids": [...], "keep_previous": false}
    keep_previous 는 v1 에서는 무시 (겸직 미지원, v2)
    """
    org = get_object_or_404(Organization, pk=pk)
    data = _parse_json(request)
    user_ids = data.get('user_ids') or []
    if not user_ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = User.objects.filter(id__in=user_ids).update(
        organization=org,
        department=org.name,
    )
    return JsonResponse({'ok': True, 'assigned': n})


@super_admin_required_api
@require_POST
def organization_remove_members_api(request, pk):
    """피그마 '소속 제외' — 선택된 사용자를 '조직 없음' 으로."""
    org = get_object_or_404(Organization, pk=pk)
    user_ids = _parse_json(request).get('user_ids') or []
    if not user_ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    company = org.parent if not org.is_root else org
    bucket = (
        company.children.filter(is_unassigned_bucket=True).first()
        if company else None
    )
    if not bucket:
        return JsonResponse(
            {'ok': False, 'error': '"조직 없음" 가상 부서를 찾을 수 없습니다.'},
            status=500,
        )
    n = User.objects.filter(id__in=user_ids, organization=org).update(
        organization=bucket,
        department=bucket.name,
    )
    return JsonResponse({'ok': True, 'removed': n})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def organization_set_leader_api(request, pk):
    """조직장 임명. body: {"user_id": ...}
    피그마: 다중 선택 시 비활성, 단건만 가능.
    """
    org = get_object_or_404(Organization, pk=pk)
    user_id = _parse_json(request).get('user_id')
    if not user_id:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    try:
        u = User.objects.get(pk=user_id, organization=org)
    except User.DoesNotExist:
        return JsonResponse(
            {'ok': False, 'error': '해당 부서 소속 사용자만 조직장 지정 가능합니다.'},
            status=400,
        )
    org.leader = u
    org.updated_by = request.user
    org.save(update_fields=['leader', 'updated_by', 'updated_at'])
    return JsonResponse({'ok': True})


@super_admin_required_api
@require_GET
def organization_member_picker_api(request):
    """구성원 선택 팝업 — 부서별 구성원 목록 제공.
    GET ?org_id=<id> → 해당 부서 구성원 (이미 그 부서면 선택 불가)
    GET (org_id 없음) → 회사 전체 구성원
    """
    org_id = request.GET.get('org_id')
    qs = User.objects.select_related('organization', 'position_obj').order_by('first_name')
    target_org_id = None
    if org_id:
        try:
            target_org_id = int(org_id)
        except ValueError:
            target_org_id = None

    payload = [{
        'id'             : u.id,
        'name'           : u.first_name,
        'username'       : u.username,
        'position'       : u.display_position,
        'organization'   : u.display_organization,
        'organization_id': u.organization_id,
        'is_in_target'   : (u.organization_id == target_org_id) if target_org_id else False,
    } for u in qs]
    return JsonResponse({'users': payload})
