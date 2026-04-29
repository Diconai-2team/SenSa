"""
backoffice/views.py — 백오피스 (슈퍼관리자 채널) 뷰

구조:
  - landing                 : /backoffice/                 (대시보드)
  - users.*                 : /backoffice/users/...        (사용자 관리)
  - organizations.*         : /backoffice/organizations/   (조직 관리)
  - positions.*             : /backoffice/positions/       (직위 관리)

페이지는 함수 뷰 + Django Template,
액션 (등록/수정/삭제/잠금/잠금해제) 은 JSON API.

브라우저는 페이지 → AJAX(fetch) → JSON 으로 모달 처리.
"""

import json

from django.db.models import Q, Case, When, IntegerField, Value
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from accounts.models import User

from .models import Organization, Position
from .forms import (
    UserCreateForm,
    UserUpdateForm,
    OrganizationForm,
    PositionForm,
)
from .permissions import super_admin_required, super_admin_required_api


# ═══════════════════════════════════════════════════════════
# 공통 — JSON 본문 파싱 + 폼 에러 직렬화
# ═══════════════════════════════════════════════════════════


def _parse_json(request) -> dict:
    """request.body 에서 JSON 디코드. 실패 시 빈 dict."""
    # AJAX 요청의 body를 UTF-8로 디코딩해서 Python dict로 반환. 빈 body나 파싱 오류면 {} 반환.
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
        # JSON 문자열 → Python dict 변환. 빈 문자열이면 '{}' 로 대체해 KeyError 방지.
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
        # UTF-8 디코딩 실패 또는 JSON 파싱 오류 시 빈 dict 반환. 예외를 밖으로 노출하지 않음.


def _form_errors_payload(form) -> dict:
    """form.errors → 프런트가 필드별로 표시하기 좋은 형태로 변환."""
    # Django form의 에러 객체를 {필드명: [에러문자열, ...]} 형태의 dict로 변환.
    # 프런트엔드에서 각 입력 필드 아래에 에러 메시지를 표시할 때 사용.
    return {
        field: [str(err) for err in errs]
        # ValidationError 객체를 문자열로 변환하여 JSON 직렬화 가능하게 만듦.
        for field, errs in form.errors.items()
    }


# ═══════════════════════════════════════════════════════════
# 랜딩 — /backoffice/
# ═══════════════════════════════════════════════════════════


@super_admin_required
def landing(request):
    """백오피스 메인 진입 화면.
    super_admin 은 무제한, admin 도 진입 가능 (개별 메뉴는 MenuPermission 으로 제어).
    """
    # admin 도 통과시키기 위해 super_admin_required 안에서 막힌 admin 을 다시 허용
    # → 데코레이터 인자 없이 호출되면 super_admin only 라서, landing 은 view 자체에서 분기
    if not (request.user.is_super_admin_role or request.user.role == "admin"):
        from django.shortcuts import render as _r

        return _r(request, "backoffice/403.html", status=403)
        # super_admin도 admin도 아닌 사용자(operator 등)가 진입하면 403 접근 거부 페이지 반환.

    ctx = {
        "stats": {
            "user_count": User.objects.count(),
            # 전체 사용자 수 — 비활성 포함 총 가입자 카운트.
            "org_count": Organization.objects.exclude(
                is_unassigned_bucket=True
            ).count(),
            # "조직 없음" 가상 부서를 제외한 실제 조직(부서) 수.
            "position_count": Position.objects.filter(is_active=True).count(),
            # 활성 상태인 직위 수.
            "locked_count": User.objects.filter(is_locked=True).count(),
            # 계정이 잠긴 사용자 수 — 대시보드에서 주의가 필요한 상태 표시.
        },
    }
    return render(request, "backoffice/landing.html", ctx)
    # 통계 수치를 context로 넘겨 랜딩 템플릿을 렌더링.


# ═══════════════════════════════════════════════════════════
# 사용자 관리 — 페이지
# ═══════════════════════════════════════════════════════════

USER_PAGE_SIZE = 10
# 사용자 목록 페이지 한 번에 표시할 행 수.

USER_SORT_OPTIONS = {
    # 정렬 키 → (DB 필드명, 표시 레이블) 매핑. 프런트 드롭다운과 서버 정렬 기준 연결.
    "name_asc": ("first_name", "사용자명 오름차순"),
    "last_login_desc": ("-last_login", "최근 로그인순"),
    "created_desc": ("-date_joined", "등록일순"),
    "role_asc": ("role", "권한순"),
    "status_asc": (None, "계정 상태순"),  # is_active+is_locked 합성, 아래에서 처리
    # 'status_asc'는 단순 필드 정렬 불가 — Case/When 어노테이션으로 아래에서 별도 처리.
}


@super_admin_required(menu_code="users")
def user_list(request):
    """사용자 관리 — 목록 페이지 + 검색/필터/정렬/페이지네이션 (서버 렌더)."""
    qs = User.objects.select_related("organization", "position_obj").all()
    # 연관 조직·직위를 JOIN으로 한 번에 가져와 N+1 쿼리 방지.

    # ── 검색 필터 ──
    q_name = request.GET.get("name", "").strip()
    q_org = request.GET.get("organization", "").strip()
    q_pos = request.GET.get("position", "").strip()
    q_role = request.GET.get("role", "").strip()
    q_status = request.GET.get("status", "").strip()
    # GET 파라미터에서 각 검색 조건을 읽어옴. .strip()으로 앞뒤 공백 제거.

    if q_name:
        qs = qs.filter(Q(first_name__icontains=q_name) | Q(username__icontains=q_name))
        # 이름 또는 아이디 어디에든 검색어가 포함되면 매칭 (대소문자 무시).
    if q_org:
        qs = qs.filter(organization_id=q_org)
        # 특정 조직 소속 사용자만 필터링.
    if q_pos:
        qs = qs.filter(position_obj_id=q_pos)
        # 특정 직위의 사용자만 필터링.
    if q_role:
        qs = qs.filter(role=q_role)
        # 특정 역할(super_admin/admin/operator)의 사용자만 필터링.
    if q_status == "active":
        qs = qs.filter(is_active=True, is_locked=False)
        # 활성 상태: 활성이면서 잠금되지 않은 사용자.
    elif q_status == "locked":
        qs = qs.filter(is_active=True, is_locked=True)
        # 잠금 상태: 활성이지만 관리자가 잠근 계정.
    elif q_status == "disabled":
        qs = qs.filter(is_active=False)
        # 비활성 상태: Django is_active=False로 비활성화된 계정.

    # ── 정렬 ──
    sort = request.GET.get("sort", "name_asc")
    if sort == "status_asc":
        # 사용(0) < 잠금(1) < 비활성(2) 순으로 정렬되도록 합성 키
        qs = qs.annotate(
            _status_key=Case(
                When(is_active=False, then=Value(2)),
                # 비활성 계정을 가장 뒤에 배치.
                When(is_active=True, is_locked=True, then=Value(1)),
                # 잠금 계정을 중간에 배치.
                default=Value(0),
                # 정상 활성 계정을 앞에 배치.
                output_field=IntegerField(),
            )
        ).order_by("_status_key", "first_name")
        # 상태 키로 먼저 정렬하고, 같은 상태 안에서는 이름 오름차순.
    else:
        order_field = USER_SORT_OPTIONS.get(sort, USER_SORT_OPTIONS["name_asc"])[0]
        qs = qs.order_by(order_field, "first_name")
        # 정렬 키에 대응하는 DB 필드로 정렬. 같은 값이면 이름 오름차순 보조 정렬.

    # ── 페이지네이션 ──
    total = qs.count()
    try:
        page = max(1, int(request.GET.get("page", 1)))
        # 페이지 번호가 1 미만이면 1로 고정.
    except ValueError:
        page = 1
        # 숫자가 아닌 page 파라미터는 1로 초기화.
    start = (page - 1) * USER_PAGE_SIZE
    rows = list(qs[start : start + USER_PAGE_SIZE])
    # 현재 페이지에 해당하는 슬라이스만 DB에서 가져옴.
    last_page = max(1, (total + USER_PAGE_SIZE - 1) // USER_PAGE_SIZE)
    # 총 페이지 수 계산. 결과가 0건이어도 최소 1페이지.

    ctx = {
        "rows": rows,
        "total": total,
        "page": page,
        "last_page": last_page,
        "page_size": USER_PAGE_SIZE,
        "page_start": start + 1 if total else 0,
        # 현재 페이지 첫 번째 항목 번호 (1-based). 결과 없으면 0.
        "page_end": min(start + USER_PAGE_SIZE, total),
        # 현재 페이지 마지막 항목 번호.
        "page_range": range(1, last_page + 1),
        # 페이지 번호 버튼 목록 생성용.
        "sort": sort,
        "sort_options": [(k, v[1]) for k, v in USER_SORT_OPTIONS.items()],
        # 드롭다운에 표시할 (정렬 키, 레이블) 목록.
        "organizations": Organization.objects.filter(parent__isnull=False).order_by(
            "sort_order"
        ),
        # 루트(회사)를 제외한 부서 목록 — 필터 드롭다운용.
        "positions": Position.objects.filter(is_active=True),
        # 활성 직위 목록 — 필터 드롭다운용.
        "roles": User.ROLE_CHOICES,
        # 역할 선택지 — 필터 드롭다운용.
        "q": {
            "name": q_name,
            "organization": q_org,
            "position": q_pos,
            "role": q_role,
            "status": q_status,
        },
        # 현재 검색 조건을 템플릿에 다시 전달해 폼 필드 값을 유지.
    }
    return render(request, "backoffice/users/list.html", ctx)


# ═══════════════════════════════════════════════════════════
# 사용자 관리 — JSON API
# ═══════════════════════════════════════════════════════════


def _user_to_dict(u: User) -> dict:
    # User 모델 인스턴스를 JSON 직렬화 가능한 dict로 변환. 모달·AJAX 응답에 사용.
    return {
        "id": u.id,
        "name": u.first_name,
        "username": u.username,
        "organization_id": u.organization_id,
        "organization": u.display_organization,
        # display_organization 프로퍼티: 조직명을 보기 좋은 문자열로 반환.
        "position_obj_id": u.position_obj_id,
        "position": u.display_position,
        # display_position 프로퍼티: 직위명 반환. 없으면 '-'.
        "role": u.role,
        "role_display": u.get_role_display(),
        # get_role_display(): Django choices에서 역할 코드를 한글 레이블로 변환.
        "account_status": u.account_status,
        "account_status_display": u.account_status_display,
        # account_status 프로퍼티: is_active/is_locked 조합으로 'active'/'locked'/'disabled' 반환.
        "email": u.email,
        "phone": u.phone,
        "last_login": (
            u.last_login.strftime("%Y-%m-%d %H:%M:%S") if u.last_login else "-"
        ),
        # 마지막 로그인 시각. 로그인 이력 없으면 '-'.
        "date_joined": u.date_joined.strftime("%Y-%m-%d") if u.date_joined else "-",
        # 계정 생성일.
    }


@super_admin_required_api(menu_code="users", action="read")
@require_GET
def user_detail_api(request, pk):
    # 단일 사용자 상세 조회 — 수정 모달 열 때 호출.
    u = get_object_or_404(
        User.objects.select_related("organization", "position_obj"),
        pk=pk,
    )
    # select_related로 조직·직위를 JOIN 조회해 추가 쿼리 없이 직렬화.
    return JsonResponse({"user": _user_to_dict(u)})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def user_create_api(request):
    # 새 사용자 생성. body의 JSON을 UserCreateForm으로 검증 후 저장.
    form = UserCreateForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
        # 검증 실패 시 필드별 에러 메시지를 400으로 반환.
    u = form.save(created_by=request.user)
    # 생성자 정보를 저장해 감사 로그에 남김.
    return JsonResponse({"ok": True, "user": _user_to_dict(u)})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def user_update_api(request, pk):
    # 기존 사용자 정보 수정. body JSON을 UserUpdateForm으로 검증 후 업데이트.
    u = get_object_or_404(User, pk=pk)
    form = UserUpdateForm(_parse_json(request), instance=u)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    u = form.save()
    return JsonResponse({"ok": True, "user": _user_to_dict(u)})


@super_admin_required_api
@require_POST
def user_bulk_delete_api(request):
    """선택된 사용자 일괄 삭제. body: {"ids": [1, 2, 3]}"""
    ids = _parse_json(request).get("ids") or []
    if not isinstance(ids, list) or not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    # 자기 자신 삭제 방지
    if request.user.id in ids:
        return JsonResponse(
            {"ok": False, "error": "본인 계정은 삭제할 수 없습니다."},
            status=400,
        )
        # 로그인한 관리자가 자신의 계정을 실수로 삭제하는 것을 막음.
    deleted, _ = User.objects.filter(id__in=ids).delete()
    # 선택된 ID 목록의 사용자를 한 번의 DELETE 쿼리로 삭제. 반환값의 첫 번째 값이 삭제 건수.
    return JsonResponse({"ok": True, "deleted": deleted})


@super_admin_required_api
@require_POST
def user_bulk_lock_api(request):
    # 선택된 사용자 일괄 잠금. is_locked=True로 업데이트.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    if request.user.id in ids:
        return JsonResponse(
            {"ok": False, "error": "본인 계정은 잠글 수 없습니다."},
            status=400,
        )
        # 관리자가 자기 자신을 잠가서 백오피스에 접근 불가가 되는 상황을 방지.
    n = User.objects.filter(id__in=ids, is_active=True).update(is_locked=True)
    # 이미 비활성된 계정은 제외하고 활성 사용자만 잠금. 업데이트 건수 반환.
    return JsonResponse({"ok": True, "locked": n})


@super_admin_required_api
@require_POST
def user_bulk_unlock_api(request):
    # 선택된 사용자 일괄 잠금 해제. is_locked=False로 업데이트.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = User.objects.filter(id__in=ids).update(is_locked=False)
    # 비활성 계정도 포함해 모두 잠금 해제 (비활성은 어차피 로그인 불가이므로 무해).
    return JsonResponse({"ok": True, "unlocked": n})


# ═══════════════════════════════════════════════════════════
# 조직 관리 — 페이지 + API
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="users")
def organization_manage(request):
    """조직 관리 메인 페이지.
    초기 진입 시 회사(root) 가 펼쳐진 상태. 부서 선택 → 우측 상세는 AJAX.
    """
    company = Organization.objects.filter(parent__isnull=True).first()
    departments = []
    if company:
        departments = list(
            company.children.exclude(is_unassigned_bucket=True).order_by("sort_order")
        )
        unassigned = company.children.filter(is_unassigned_bucket=True).first()
        if unassigned:
            departments.append(unassigned)

    ctx = {
        "company": company,
        "departments": departments,
    }
    return render(request, "backoffice/organizations/manage.html", ctx)


def _org_to_dict(org: Organization) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "code": org.code,
        "parent_id": org.parent_id,
        "description": org.description,
        "leader_id": org.leader_id,
        "leader_name": org.leader.first_name if org.leader else None,
        "is_unassigned_bucket": org.is_unassigned_bucket,
        "is_root": org.is_root,
        "member_count": org.member_count,
        "updated_at": (
            org.updated_at.strftime("%Y-%m-%d %H:%M") if org.updated_at else "-"
        ),
        "updated_by_name": org.updated_by.first_name if org.updated_by else "-",
    }


@super_admin_required_api
@require_GET
def organization_detail_api(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    members = org.users.select_related("position_obj").order_by("-id")
    members_data = [
        {
            "id": u.id,
            "name": u.first_name,
            "username": u.username,
            "position": u.display_position,
            "account_status": u.account_status,
            "account_status_display": u.account_status_display,
            "is_leader": (u.id == org.leader_id),
        }
        for u in members
    ]

    return JsonResponse(
        {
            "organization": _org_to_dict(org),
            "members": members_data,
        }
    )


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def organization_create_api(request):
    form = OrganizationForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    org = form.save(by=request.user)
    return JsonResponse({"ok": True, "organization": _org_to_dict(org)})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def organization_update_api(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    if org.is_unassigned_bucket:
        return JsonResponse(
            {"ok": False, "error": '"조직 없음" 가상 부서는 수정할 수 없습니다.'},
            status=400,
        )
    form = OrganizationForm(_parse_json(request), instance=org)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    org = form.save(by=request.user)
    return JsonResponse({"ok": True, "organization": _org_to_dict(org)})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def organization_delete_api(request, pk):
    """부서 삭제. 소속 사용자는 '조직 없음' 으로 자동 이동."""
    org = get_object_or_404(Organization, pk=pk)
    if org.is_unassigned_bucket:
        return JsonResponse(
            {"ok": False, "error": '"조직 없음" 가상 부서는 삭제할 수 없습니다.'},
            status=400,
        )
    if org.is_root:
        return JsonResponse(
            {"ok": False, "error": "회사(루트) 노드는 삭제할 수 없습니다."},
            status=400,
        )
    # 소속 사용자 → 조직 없음 으로 이동
    company = org.parent
    bucket = (
        company.children.filter(is_unassigned_bucket=True).first() if company else None
    )
    if bucket:
        org.users.update(organization=bucket)

    org.delete()
    return JsonResponse({"ok": True})


@super_admin_required_api
@require_POST
def organization_assign_members_api(request, pk):
    """피그마 '구성원 추가' — 다른 부서 사용자를 이 부서로 옮김(또는 겸직).
    body: {"user_ids": [...], "keep_previous": false}
    keep_previous 는 v1 에서는 무시 (겸직 미지원, v2)
    """
    org = get_object_or_404(Organization, pk=pk)
    data = _parse_json(request)
    user_ids = data.get("user_ids") or []
    if not user_ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = User.objects.filter(id__in=user_ids).update(
        organization=org,
        department=org.name,
    )
    return JsonResponse({"ok": True, "assigned": n})


@super_admin_required_api
@require_POST
def organization_remove_members_api(request, pk):
    """피그마 '소속 제외' — 선택된 사용자를 '조직 없음' 으로."""
    org = get_object_or_404(Organization, pk=pk)
    user_ids = _parse_json(request).get("user_ids") or []
    if not user_ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    company = org.parent if not org.is_root else org
    bucket = (
        company.children.filter(is_unassigned_bucket=True).first() if company else None
    )
    if not bucket:
        return JsonResponse(
            {"ok": False, "error": '"조직 없음" 가상 부서를 찾을 수 없습니다.'},
            status=500,
        )
    n = User.objects.filter(id__in=user_ids, organization=org).update(
        organization=bucket,
        department=bucket.name,
    )
    return JsonResponse({"ok": True, "removed": n})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def organization_set_leader_api(request, pk):
    """조직장 임명. body: {"user_id": ...}
    피그마: 다중 선택 시 비활성, 단건만 가능.
    """
    org = get_object_or_404(Organization, pk=pk)
    user_id = _parse_json(request).get("user_id")
    if not user_id:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    try:
        u = User.objects.get(pk=user_id, organization=org)
    except User.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": "해당 부서 소속 사용자만 조직장 지정 가능합니다."},
            status=400,
        )
    org.leader = u
    org.updated_by = request.user
    org.save(update_fields=["leader", "updated_by", "updated_at"])
    return JsonResponse({"ok": True})


@super_admin_required_api
@require_GET
def organization_member_picker_api(request):
    """구성원 선택 팝업 — 부서별 구성원 목록 제공.
    GET ?org_id=<id> → 해당 부서 구성원 (이미 그 부서면 선택 불가)
    GET (org_id 없음) → 회사 전체 구성원
    """
    org_id = request.GET.get("org_id")
    qs = User.objects.select_related("organization", "position_obj").order_by(
        "first_name"
    )
    target_org_id = None
    if org_id:
        try:
            target_org_id = int(org_id)
        except ValueError:
            target_org_id = None

    payload = [
        {
            "id": u.id,
            "name": u.first_name,
            "username": u.username,
            "position": u.display_position,
            "organization": u.display_organization,
            "organization_id": u.organization_id,
            "is_in_target": (
                (u.organization_id == target_org_id) if target_org_id else False
            ),
        }
        for u in qs
    ]
    return JsonResponse({"users": payload})


# ═══════════════════════════════════════════════════════════
# 직위 관리 — 페이지 + API
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="users")
def position_list(request):
    q = request.GET.get("q", "").strip()
    qs = Position.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
    qs = qs.order_by("sort_order", "name")
    return render(
        request,
        "backoffice/positions/list.html",
        {
            "rows": list(qs),
            "q": q,
        },
    )


def _position_to_dict(p: Position) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "description": p.description,
        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else "-",
    }


@super_admin_required_api(menu_code="users", action="read")
@require_GET
def position_detail_api(request, pk):
    p = get_object_or_404(Position, pk=pk)
    return JsonResponse({"position": _position_to_dict(p)})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def position_create_api(request):
    form = PositionForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "position": _position_to_dict(p)})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def position_update_api(request, pk):
    p = get_object_or_404(Position, pk=pk)
    form = PositionForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "position": _position_to_dict(p)})


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def position_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Position.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


# ═══════════════════════════════════════════════════════════
# 코어 마스터 — 공통 코드 / 위험 유형 / 위험 기준 / 임계치
# ═══════════════════════════════════════════════════════════
from .models import (
    CodeGroup,
    Code,
    RiskCategory,
    RiskType,
    AlarmLevel,
    ThresholdCategory,
    Threshold,
)
from .forms import (
    CodeGroupForm,
    CodeForm,
    RiskCategoryForm,
    RiskTypeForm,
    AlarmLevelForm,
    ThresholdCategoryForm,
    ThresholdForm,
)


# ───────────────── 공통 코드 ─────────────────


@super_admin_required(menu_code="references")
def code_manage(request):
    """공통 코드 관리 — 그룹 트리 + 그룹별 코드 목록.
    피그마와 동일한 좌(그룹) 우(코드 목록) 2-패널.
    """
    groups = list(CodeGroup.objects.all().order_by("sort_order", "code"))
    return render(
        request,
        "backoffice/codes/manage.html",
        {
            "groups": groups,
            "active_menu": "codes",
        },
    )


def _code_group_to_dict(g: CodeGroup) -> dict:
    return {
        "id": g.id,
        "code": g.code,
        "name": g.name,
        "description": g.description,
        "sort_order": g.sort_order,
        "is_active": g.is_active,
        "is_system": g.is_system,
        "code_count": g.code_count,
        "updated_at": g.updated_at.strftime("%Y-%m-%d %H:%M") if g.updated_at else "-",
        "updated_by_name": g.updated_by.first_name if g.updated_by else "-",
    }


def _code_to_dict(c: Code) -> dict:
    return {
        "id": c.id,
        "group_id": c.group_id,
        "code": c.code,
        "name": c.name,
        "description": c.description,
        "sort_order": c.sort_order,
        "is_active": c.is_active,
        "updated_at": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "-",
    }


@super_admin_required_api(menu_code="references", action="read")
@require_GET
def code_group_detail_api(request, pk):
    g = get_object_or_404(CodeGroup, pk=pk)
    codes = [_code_to_dict(c) for c in g.codes.order_by("sort_order", "code")]
    return JsonResponse({"group": _code_group_to_dict(g), "codes": codes})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_group_create_api(request):
    form = CodeGroupForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save(by=request.user)
    return JsonResponse({"ok": True, "group": _code_group_to_dict(g)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_group_update_api(request, pk):
    g = get_object_or_404(CodeGroup, pk=pk)
    form = CodeGroupForm(_parse_json(request), instance=g)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save(by=request.user)
    return JsonResponse({"ok": True, "group": _code_group_to_dict(g)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_group_delete_api(request, pk):
    g = get_object_or_404(CodeGroup, pk=pk)
    if g.is_system:
        return JsonResponse(
            {"ok": False, "error": "시스템 코드 그룹은 삭제할 수 없습니다."},
            status=400,
        )
    g.delete()
    return JsonResponse({"ok": True})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_create_api(request):
    form = CodeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "code": _code_to_dict(c)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_update_api(request, pk):
    c = get_object_or_404(Code, pk=pk)
    form = CodeForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "code": _code_to_dict(c)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Code.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_bulk_toggle_api(request):
    """is_active 일괄 변경. body: {"ids": [...], "is_active": false}"""
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Code.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({"ok": True, "updated": n})


# ───────────────── 위험 유형 ─────────────────


@super_admin_required(menu_code="references")
def risk_manage(request):
    cats = list(RiskCategory.objects.all().order_by("sort_order", "code"))
    return render(
        request,
        "backoffice/risks/manage.html",
        {
            "categories": cats,
            "active_menu": "risks",
        },
    )


def _risk_cat_to_dict(c: RiskCategory) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "description": c.description,
        "applies_to": c.applies_to,
        "applies_to_list": c.applies_to_list,
        "sort_order": c.sort_order,
        "is_active": c.is_active,
        "is_system": c.is_system,
        "type_count": c.type_count,
        "updated_at": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "-",
        "updated_by_name": c.updated_by.first_name if c.updated_by else "-",
    }


def _risk_type_to_dict(t: RiskType) -> dict:
    return {
        "id": t.id,
        "category_id": t.category_id,
        "code": t.code,
        "name": t.name,
        "description": t.description,
        "show_on_map": t.show_on_map,
        "sort_order": t.sort_order,
        "is_active": t.is_active,
        "updated_at": t.updated_at.strftime("%Y-%m-%d %H:%M") if t.updated_at else "-",
    }


@super_admin_required_api(menu_code="references", action="read")
@require_GET
def risk_cat_detail_api(request, pk):
    c = get_object_or_404(RiskCategory, pk=pk)
    types = [_risk_type_to_dict(t) for t in c.types.order_by("sort_order", "code")]
    return JsonResponse({"category": _risk_cat_to_dict(c), "types": types})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_cat_create_api(request):
    form = RiskCategoryForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _risk_cat_to_dict(c)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_cat_update_api(request, pk):
    c = get_object_or_404(RiskCategory, pk=pk)
    form = RiskCategoryForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _risk_cat_to_dict(c)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_cat_delete_api(request, pk):
    c = get_object_or_404(RiskCategory, pk=pk)
    if c.is_system:
        return JsonResponse(
            {"ok": False, "error": "시스템 분류는 삭제할 수 없습니다."}, status=400
        )
    c.delete()
    return JsonResponse({"ok": True})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_type_create_api(request):
    form = RiskTypeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "type": _risk_type_to_dict(t)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_type_update_api(request, pk):
    t = get_object_or_404(RiskType, pk=pk)
    form = RiskTypeForm(_parse_json(request), instance=t)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "type": _risk_type_to_dict(t)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_type_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = RiskType.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


# ───────────────── 위험 기준 (알람 단계) ─────────────────


@super_admin_required(menu_code="references")
def alarm_level_list(request):
    rows = list(AlarmLevel.objects.all().order_by("priority", "code"))
    return render(
        request,
        "backoffice/alarm_levels/list.html",
        {
            "rows": rows,
            "active_menu": "alarm_levels",
        },
    )


def _alarm_to_dict(a: AlarmLevel) -> dict:
    return {
        "id": a.id,
        "code": a.code,
        "name": a.name,
        "color": a.color,
        "color_display": a.get_color_display(),
        "intensity": a.intensity,
        "intensity_display": a.get_intensity_display(),
        "priority": a.priority,
        "description": a.description,
        "is_active": a.is_active,
        "is_system": a.is_system,
        "updated_at": a.updated_at.strftime("%Y-%m-%d %H:%M") if a.updated_at else "-",
    }


@super_admin_required_api(menu_code="references", action="read")
@require_GET
def alarm_level_detail_api(request, pk):
    a = get_object_or_404(AlarmLevel, pk=pk)
    return JsonResponse({"alarm_level": _alarm_to_dict(a)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def alarm_level_create_api(request):
    form = AlarmLevelForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    a = form.save(by=request.user)
    return JsonResponse({"ok": True, "alarm_level": _alarm_to_dict(a)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def alarm_level_update_api(request, pk):
    a = get_object_or_404(AlarmLevel, pk=pk)
    form = AlarmLevelForm(_parse_json(request), instance=a)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    a = form.save(by=request.user)
    return JsonResponse({"ok": True, "alarm_level": _alarm_to_dict(a)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def alarm_level_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    # 시스템 레벨 보호
    sys_ids = list(
        AlarmLevel.objects.filter(id__in=ids, is_system=True).values_list(
            "id", flat=True
        )
    )
    if sys_ids:
        return JsonResponse(
            {
                "ok": False,
                "error": f"시스템 단계 {len(sys_ids)}개는 삭제할 수 없습니다.",
            },
            status=400,
        )
    deleted, _ = AlarmLevel.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


# ───────────────── 임계치 기준 ─────────────────


@super_admin_required(menu_code="references")
def threshold_manage(request):
    cats = list(ThresholdCategory.objects.all().order_by("sort_order", "code"))
    return render(
        request,
        "backoffice/thresholds/manage.html",
        {
            "categories": cats,
            "active_menu": "thresholds",
        },
    )


def _th_cat_to_dict(c: ThresholdCategory) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "description": c.description,
        "applies_to": c.applies_to,
        "applies_to_list": c.applies_to_list,
        "sort_order": c.sort_order,
        "is_active": c.is_active,
        "is_system": c.is_system,
        "threshold_count": c.threshold_count,
        "updated_at": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "-",
        "updated_by_name": c.updated_by.first_name if c.updated_by else "-",
    }


def _th_to_dict(t: Threshold) -> dict:
    return {
        "id": t.id,
        "category_id": t.category_id,
        "item_code": t.item_code,
        "item_name": t.item_name,
        "unit": t.unit,
        "operator": t.operator,
        "operator_display": t.get_operator_display(),
        "caution_value": t.caution_value,
        "danger_value": t.danger_value,
        "is_active": t.is_active,
        "applies_to": t.applies_to,
        "applies_to_list": t.applies_to_list,
        "description": t.description,
        "updated_at": t.updated_at.strftime("%Y-%m-%d %H:%M") if t.updated_at else "-",
    }


@super_admin_required_api(menu_code="references", action="read")
@require_GET
def threshold_cat_detail_api(request, pk):
    c = get_object_or_404(ThresholdCategory, pk=pk)
    items = [_th_to_dict(t) for t in c.thresholds.order_by("item_code")]
    return JsonResponse({"category": _th_cat_to_dict(c), "thresholds": items})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_cat_create_api(request):
    form = ThresholdCategoryForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _th_cat_to_dict(c)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_cat_update_api(request, pk):
    c = get_object_or_404(ThresholdCategory, pk=pk)
    form = ThresholdCategoryForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _th_cat_to_dict(c)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_create_api(request):
    form = ThresholdForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "threshold": _th_to_dict(t)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_update_api(request, pk):
    t = get_object_or_404(Threshold, pk=pk)
    form = ThresholdForm(_parse_json(request), instance=t)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "threshold": _th_to_dict(t)})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Threshold.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Threshold.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({"ok": True, "updated": n})


# ───────────────── FastAPI 동기화용 내부 API ─────────────────
#
# /dashboard/api/thresholds/  →  FastAPI 가 호출하여 GAS_THRESHOLDS 대체
#
# 인증: 세션 인증 (Django) 또는 INTERNAL_API_KEY (FastAPI 가 호출 시).
# 응답 포맷: 기존 GAS_THRESHOLDS 와 호환되는 dict 구조 + 추가 메타.

from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
@require_GET
def thresholds_for_fastapi(request):
    """FastAPI 가 startup / 주기 갱신 시 호출하는 동기화 엔드포인트.

    InternalAPIKeyMiddleware 가 internal key 또는 세션 인증을 통과시킴.
    응답:
      {
        "categories": {
          "TH_GAS": {
            "code": "TH_GAS", "name": "유해가스",
            "applies_to": ["realtime", "alarm"],
            "thresholds": [ {item_code, item_name, unit, operator, caution, danger, applies_to}, ... ]
          },
          ...
        },
        "flat": { item_code: {...같은 entry...}, ... }   # generators.py 직접 lookup 용
      }
    """
    cats = ThresholdCategory.objects.filter(is_active=True).prefetch_related(
        "thresholds"
    )
    payload = {"categories": {}, "flat": {}}
    for cat in cats:
        cat_obj = {
            "code": cat.code,
            "name": cat.name,
            "applies_to": cat.applies_to_list,
            "thresholds": [],
        }
        for t in cat.thresholds.filter(is_active=True):
            entry = {
                "category_code": cat.code,
                "item_code": t.item_code,
                "item_name": t.item_name,
                "unit": t.unit,
                "operator": t.operator,
                "caution": t.caution_value,
                "danger": t.danger_value,
                "applies_to": t.applies_to_list,
            }
            cat_obj["thresholds"].append(entry)
            # flat 은 (category_code, item_code) 조합 키 — 다른 카테고리에 같은 item_code 가 있을 수 있으므로
            payload["flat"][f"{cat.code}.{t.item_code}"] = entry

        payload["categories"][cat.code] = cat_obj

    return JsonResponse(payload)


# ═══════════════════════════════════════════════════════════
# 이벤트 이력 (Alarm 조회) — 피그마 '이벤트 이력 관리'
# ═══════════════════════════════════════════════════════════
import csv
from datetime import datetime, timedelta
from django.http import HttpResponse
from django.utils import timezone

from alerts.models import Alarm, ALARM_LEVEL_CHOICES, ALARM_TYPE_CHOICES

from .models import (
    NotificationPolicy,
    NotificationLog,
    MenuPermission,
    NOTIFICATION_CHANNEL_CHOICES,
    MENU_CODE_CHOICES,
)
from .forms import NotificationPolicyForm, MenuPermissionUpdateForm


EVENT_PAGE_SIZE = 20


@super_admin_required(menu_code="notifications")
def event_history(request):
    """이벤트 이력 조회 페이지 — 검색/필터/정렬/페이지네이션.
    피그마: 알람 발생 일시·레벨·작업자·장비·메시지·읽음 상태 컬럼.
    """
    qs = Alarm.objects.all()

    q_level = request.GET.get("level", "").strip()
    q_type = request.GET.get("type", "").strip()
    q_keyword = request.GET.get("keyword", "").strip()
    q_from = request.GET.get("from", "").strip()
    q_to = request.GET.get("to", "").strip()
    q_unread = request.GET.get("unread", "").strip()

    if q_level:
        qs = qs.filter(alarm_level=q_level)
    if q_type:
        qs = qs.filter(alarm_type=q_type)
    if q_keyword:
        qs = qs.filter(
            Q(message__icontains=q_keyword)
            | Q(worker_name__icontains=q_keyword)
            | Q(worker_id__icontains=q_keyword)
            | Q(device_id__icontains=q_keyword)
        )
    if q_unread == "1":
        qs = qs.filter(is_read=False)
    if q_from:
        try:
            dt = datetime.strptime(q_from, "%Y-%m-%d")
            qs = qs.filter(created_at__gte=timezone.make_aware(dt))
        except ValueError:
            pass
    if q_to:
        try:
            dt = datetime.strptime(q_to, "%Y-%m-%d") + timedelta(days=1)
            qs = qs.filter(created_at__lt=timezone.make_aware(dt))
        except ValueError:
            pass

    qs = qs.order_by("-created_at")
    total = qs.count()

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * EVENT_PAGE_SIZE
    rows = list(qs[start : start + EVENT_PAGE_SIZE])
    last_page = max(1, (total + EVENT_PAGE_SIZE - 1) // EVENT_PAGE_SIZE)

    return render(
        request,
        "backoffice/events/list.html",
        {
            "rows": rows,
            "total": total,
            "page": page,
            "last_page": last_page,
            "page_start": start + 1 if total else 0,
            "page_end": min(start + EVENT_PAGE_SIZE, total),
            "page_range": range(max(1, page - 4), min(last_page, page + 4) + 1),
            "levels": ALARM_LEVEL_CHOICES,
            "types": ALARM_TYPE_CHOICES,
            "q": {
                "level": q_level,
                "type": q_type,
                "keyword": q_keyword,
                "from": q_from,
                "to": q_to,
                "unread": q_unread,
            },
            "active_menu": "events",
        },
    )


@super_admin_required(menu_code="notifications")
def event_history_csv(request):
    """현재 검색 조건의 이벤트 이력을 CSV 다운로드. 페이지네이션 무시."""
    qs = Alarm.objects.all()
    # 위 view 와 동일한 필터 (DRY 위반은 의도 — 페이지네이션 빼고 동일)
    q_level = request.GET.get("level", "").strip()
    q_type = request.GET.get("type", "").strip()
    q_keyword = request.GET.get("keyword", "").strip()
    q_from = request.GET.get("from", "").strip()
    q_to = request.GET.get("to", "").strip()
    q_unread = request.GET.get("unread", "").strip()
    if q_level:
        qs = qs.filter(alarm_level=q_level)
    if q_type:
        qs = qs.filter(alarm_type=q_type)
    if q_keyword:
        qs = qs.filter(
            Q(message__icontains=q_keyword)
            | Q(worker_name__icontains=q_keyword)
            | Q(worker_id__icontains=q_keyword)
            | Q(device_id__icontains=q_keyword)
        )
    if q_unread == "1":
        qs = qs.filter(is_read=False)
    if q_from:
        try:
            dt = datetime.strptime(q_from, "%Y-%m-%d")
            qs = qs.filter(created_at__gte=timezone.make_aware(dt))
        except ValueError:
            pass
    if q_to:
        try:
            dt = datetime.strptime(q_to, "%Y-%m-%d") + timedelta(days=1)
            qs = qs.filter(created_at__lt=timezone.make_aware(dt))
        except ValueError:
            pass
    qs = qs.order_by("-created_at")

    # CSV 응답 — UTF-8 BOM 으로 Excel 한글 깨짐 방지
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    filename = f"events_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # BOM
    writer = csv.writer(response)
    writer.writerow(
        [
            "발생일시",
            "레벨",
            "유형",
            "작업자ID",
            "작업자명",
            "장비ID",
            "센서타입",
            "메시지",
            "읽음",
        ]
    )
    for a in qs.iterator(chunk_size=500):
        writer.writerow(
            [
                a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                a.get_alarm_level_display(),
                a.get_alarm_type_display(),
                a.worker_id,
                a.worker_name,
                a.device_id,
                a.sensor_type,
                a.message,
                "읽음" if a.is_read else "안읽음",
            ]
        )
    return response


@super_admin_required_api(menu_code="notifications", action="read")
@require_GET
def event_detail_api(request, pk):
    """이벤트 1건 상세 — 모달용."""
    a = get_object_or_404(Alarm, pk=pk)
    return JsonResponse(
        {
            "event": {
                "id": a.id,
                "created_at": a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "alarm_level": a.alarm_level,
                "alarm_level_display": a.get_alarm_level_display(),
                "alarm_type": a.alarm_type,
                "alarm_type_display": a.get_alarm_type_display(),
                "worker_id": a.worker_id,
                "worker_name": a.worker_name,
                "worker_x": a.worker_x,
                "worker_y": a.worker_y,
                "device_id": a.device_id,
                "sensor_type": a.sensor_type,
                "message": a.message,
                "is_read": a.is_read,
                "geofence_name": a.geofence.name if a.geofence else None,
            }
        }
    )


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def event_bulk_read_api(request):
    """선택 이벤트 일괄 읽음 처리."""
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Alarm.objects.filter(id__in=ids, is_read=False).update(is_read=True)
    return JsonResponse({"ok": True, "updated": n})


# ═══════════════════════════════════════════════════════════
# 알림 정책 관리
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="notifications")
def notification_policy_list(request):
    rows = list(
        NotificationPolicy.objects.select_related("risk_category", "alarm_level").all()
    )
    return render(
        request,
        "backoffice/notifications/policy_list.html",
        {
            "rows": rows,
            "risk_categories": RiskCategory.objects.filter(is_active=True),
            "alarm_levels": AlarmLevel.objects.filter(is_active=True).order_by(
                "priority"
            ),
            "organizations": Organization.objects.filter(
                parent__isnull=False, is_unassigned_bucket=False
            ),
            "channel_choices": NOTIFICATION_CHANNEL_CHOICES,
            "active_menu": "notification_policies",
        },
    )


def _policy_to_dict(p: NotificationPolicy) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "description": p.description,
        "risk_category_id": p.risk_category_id,
        "risk_category_name": p.risk_category.name,
        "alarm_level_id": p.alarm_level_id,
        "alarm_level_name": p.alarm_level.name,
        "channels_csv": p.channels_csv,
        "channels_list": p.channels_list,
        "recipients_csv": p.recipients_csv,
        "recipients_list": p.recipients_list,
        "message_template": p.message_template,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else "-",
    }


@super_admin_required_api(menu_code="notifications", action="read")
@require_GET
def policy_detail_api(request, pk):
    p = get_object_or_404(
        NotificationPolicy.objects.select_related("risk_category", "alarm_level"),
        pk=pk,
    )
    return JsonResponse({"policy": _policy_to_dict(p)})


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_create_api(request):
    form = NotificationPolicyForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "policy": _policy_to_dict(p)})


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_update_api(request, pk):
    p = get_object_or_404(NotificationPolicy, pk=pk)
    form = NotificationPolicyForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "policy": _policy_to_dict(p)})


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = NotificationPolicy.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = NotificationPolicy.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({"ok": True, "updated": n})


# ═══════════════════════════════════════════════════════════
# 알림 발송 이력
# ═══════════════════════════════════════════════════════════

NOTIF_LOG_PAGE_SIZE = 30


@super_admin_required(menu_code="notifications")
def notification_log_list(request):
    qs = NotificationLog.objects.select_related("policy", "recipient", "alarm").all()

    q_status = request.GET.get("status", "").strip()
    q_channel = request.GET.get("channel", "").strip()
    q_keyword = request.GET.get("keyword", "").strip()
    q_from = request.GET.get("from", "").strip()
    q_to = request.GET.get("to", "").strip()

    if q_status:
        qs = qs.filter(send_status=q_status)
    if q_channel:
        qs = qs.filter(channel=q_channel)
    if q_keyword:
        qs = qs.filter(
            Q(recipient_name_snapshot__icontains=q_keyword)
            | Q(error_message__icontains=q_keyword)
            | Q(policy__name__icontains=q_keyword)
        )
    if q_from:
        try:
            dt = datetime.strptime(q_from, "%Y-%m-%d")
            qs = qs.filter(created_at__gte=timezone.make_aware(dt))
        except ValueError:
            pass
    if q_to:
        try:
            dt = datetime.strptime(q_to, "%Y-%m-%d") + timedelta(days=1)
            qs = qs.filter(created_at__lt=timezone.make_aware(dt))
        except ValueError:
            pass

    qs = qs.order_by("-created_at")
    total = qs.count()

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * NOTIF_LOG_PAGE_SIZE
    rows = list(qs[start : start + NOTIF_LOG_PAGE_SIZE])
    last_page = max(1, (total + NOTIF_LOG_PAGE_SIZE - 1) // NOTIF_LOG_PAGE_SIZE)

    # 통계 (전체 + 24시간)
    since_24h = timezone.now() - timedelta(hours=24)
    stats_24h = NotificationLog.objects.filter(created_at__gte=since_24h)
    stats = {
        "total": total,
        "sent_24h": stats_24h.filter(send_status="sent").count(),
        "failed_24h": stats_24h.filter(send_status="failed").count(),
        "pending_24h": stats_24h.filter(send_status="pending").count(),
    }

    return render(
        request,
        "backoffice/notifications/log_list.html",
        {
            "rows": rows,
            "total": total,
            "stats": stats,
            "page": page,
            "last_page": last_page,
            "page_start": start + 1 if total else 0,
            "page_end": min(start + NOTIF_LOG_PAGE_SIZE, total),
            "page_range": range(max(1, page - 4), min(last_page, page + 4) + 1),
            "channel_choices": NOTIFICATION_CHANNEL_CHOICES,
            "status_choices": NotificationLog.SEND_STATUS_CHOICES,
            "q": {
                "status": q_status,
                "channel": q_channel,
                "keyword": q_keyword,
                "from": q_from,
                "to": q_to,
            },
            "active_menu": "notification_logs",
        },
    )


# ═══════════════════════════════════════════════════════════
# 메뉴 관리
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="menus")
def menu_management(request):
    """역할 ↔ 메뉴 매트릭스. super_admin 은 항상 전체.
    admin 만 토글 가능.
    """
    perms = MenuPermission.objects.filter(role="admin")
    perm_map = {p.menu_code: p for p in perms}
    rows = []
    for code, label in MENU_CODE_CHOICES:
        p = perm_map.get(code)
        rows.append(
            {
                "menu_code": code,
                "menu_name": label,
                "is_visible": p.is_visible if p else False,
                "is_writable": p.is_writable if p else False,
                "updated_at": (
                    p.updated_at.strftime("%Y-%m-%d %H:%M")
                    if p and p.updated_at
                    else "-"
                ),
            }
        )
    return render(
        request,
        "backoffice/menus/manage.html",
        {
            "rows": rows,
            "active_menu": "menus",
        },
    )


@super_admin_required_api(menu_code="menus", action="write")
@require_POST
def menu_perm_update_api(request):
    """단일 권한 토글. body: {role, menu_code, is_visible, is_writable}"""
    data = _parse_json(request)
    form = MenuPermissionUpdateForm(data)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    role = form.cleaned_data["role"]
    menu_code = form.cleaned_data["menu_code"]

    p, _ = MenuPermission.objects.get_or_create(role=role, menu_code=menu_code)
    # 명시적 토글 - is_writable 은 is_visible 일 때만 의미가 있어 강제
    is_visible = bool(data.get("is_visible"))
    is_writable = bool(data.get("is_writable")) and is_visible
    p.is_visible = is_visible
    p.is_writable = is_writable
    p.updated_by = request.user
    p.save()
    return JsonResponse(
        {
            "ok": True,
            "perm": {
                "role": p.role,
                "menu_code": p.menu_code,
                "is_visible": p.is_visible,
                "is_writable": p.is_writable,
                "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M"),
            },
        }
    )


# ═══════════════════════════════════════════════════════════
# 설비/장비 관리 — 피그마 '설비/장비 관리'
# ═══════════════════════════════════════════════════════════
from devices.models import Device, SENSOR_TYPE_CHOICES as DEVICE_SENSOR_TYPE_CHOICES
from geofence.models import GeoFence, ZONE_TYPE_CHOICES, RISK_LEVEL_CHOICES
from dashboard.models import MapImage

from .models import DataRetentionPolicy, Notice, NOTICE_CATEGORY_CHOICES
from .forms import DeviceForm, GeoFenceForm, DataRetentionForm, NoticeForm


DEVICE_PAGE_SIZE = 20


@super_admin_required(menu_code="devices")
def device_list(request):
    qs = Device.objects.select_related("geofence").all()

    q_keyword = request.GET.get("keyword", "").strip()
    q_type = request.GET.get("type", "").strip()
    q_status = request.GET.get("status", "").strip()
    q_active = request.GET.get("active", "").strip()

    if q_keyword:
        qs = qs.filter(
            Q(device_id__icontains=q_keyword) | Q(device_name__icontains=q_keyword)
        )
    if q_type:
        qs = qs.filter(sensor_type=q_type)
    if q_status:
        qs = qs.filter(status=q_status)
    if q_active == "1":
        qs = qs.filter(is_active=True)
    elif q_active == "0":
        qs = qs.filter(is_active=False)

    qs = qs.order_by("device_id")
    total = qs.count()

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * DEVICE_PAGE_SIZE
    rows = list(qs[start : start + DEVICE_PAGE_SIZE])
    last_page = max(1, (total + DEVICE_PAGE_SIZE - 1) // DEVICE_PAGE_SIZE)

    return render(
        request,
        "backoffice/devices/list.html",
        {
            "rows": rows,
            "total": total,
            "page": page,
            "last_page": last_page,
            "page_start": start + 1 if total else 0,
            "page_end": min(start + DEVICE_PAGE_SIZE, total),
            "page_range": range(max(1, page - 4), min(last_page, page + 4) + 1),
            "sensor_types": DEVICE_SENSOR_TYPE_CHOICES,
            "geofences": GeoFence.objects.all().order_by("name"),
            "q": {
                "keyword": q_keyword,
                "type": q_type,
                "status": q_status,
                "active": q_active,
            },
            "active_menu": "devices",
        },
    )


def _device_to_dict(d: Device) -> dict:
    return {
        "id": d.id,
        "device_id": d.device_id,
        "device_name": d.device_name,
        "sensor_type": d.sensor_type,
        "sensor_type_display": d.get_sensor_type_display(),
        "x": d.x,
        "y": d.y,
        "status": d.status,
        "status_display": d.get_status_display(),
        "last_value": d.last_value,
        "last_value_unit": d.last_value_unit,
        "is_active": d.is_active,
        "geofence_id": d.geofence_id,
        "geofence_name": d.geofence.name if d.geofence else None,
    }


@super_admin_required_api(menu_code="devices", action="read")
@require_GET
def device_detail_api(request, pk):
    d = get_object_or_404(Device.objects.select_related("geofence"), pk=pk)
    return JsonResponse({"device": _device_to_dict(d)})


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_create_api(request):
    form = DeviceForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    d = form.save(by=request.user)
    return JsonResponse({"ok": True, "device": _device_to_dict(d)})


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_update_api(request, pk):
    d = get_object_or_404(Device, pk=pk)
    form = DeviceForm(_parse_json(request), instance=d)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    d = form.save(by=request.user)
    return JsonResponse({"ok": True, "device": _device_to_dict(d)})


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Device.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Device.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({"ok": True, "updated": n})


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_auto_map_geofence_api(request):
    """현재 좌표 기준으로 모든 장비의 geofence 를 자동 매핑.
    기존 매핑이 있어도 강제 재계산.
    """
    from .geo_utils import find_containing_geofence

    active_fences = list(GeoFence.objects.filter(is_active=True))
    updated = 0
    cleared = 0
    for d in Device.objects.all():
        matched = find_containing_geofence(d.x, d.y, active_fences)
        if matched and d.geofence_id != matched.id:
            d.geofence = matched
            d.save(update_fields=["geofence"])
            updated += 1
        elif not matched and d.geofence_id is not None:
            d.geofence = None
            d.save(update_fields=["geofence"])
            cleared += 1
    return JsonResponse({"ok": True, "mapped": updated, "cleared": cleared})


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_csv_upload_api(request):
    """CSV 일괄 등록.

    [v6] mode=create (default) | upsert + DeviceHistory 자동 기록.
    형식: device_id,device_name,sensor_type,x,y,is_active,last_value_unit
    """
    if "file" not in request.FILES:
        return JsonResponse(
            {"ok": False, "error": "파일이 첨부되지 않았습니다."}, status=400
        )
    f = request.FILES["file"]
    if f.size > 5 * 1024 * 1024:
        return JsonResponse(
            {"ok": False, "error": "파일 크기는 5MB 이하여야 합니다."}, status=400
        )

    mode = (request.POST.get("mode") or "create").strip().lower()
    if mode not in ("create", "upsert"):
        return JsonResponse(
            {"ok": False, "error": "mode 는 'create' 또는 'upsert' 여야 합니다."},
            status=400,
        )

    try:
        text = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return JsonResponse(
            {"ok": False, "error": "UTF-8 로 인코딩된 CSV 파일이어야 합니다."},
            status=400,
        )

    import csv as _csv
    import io as _io

    reader = _csv.DictReader(_io.StringIO(text))
    if reader.fieldnames and reader.fieldnames[0].startswith("\ufeff"):
        reader.fieldnames[0] = reader.fieldnames[0][1:]
    required = {"device_id", "device_name", "sensor_type", "x", "y"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        return JsonResponse(
            {
                "ok": False,
                "error": f"필수 컬럼이 빠졌습니다: {sorted(required - set(reader.fieldnames or []))}",
            },
            status=400,
        )

    valid_types = {c[0] for c in DEVICE_SENSOR_TYPE_CHOICES}
    created, updated, skipped, errors = 0, 0, 0, []
    existing_by_id = {d.device_id: d for d in Device.objects.all()}

    from .geo_utils import find_containing_geofence
    from .audit import write_device_history

    active_fences = list(GeoFence.objects.filter(is_active=True))

    for line_no, row in enumerate(reader, start=2):
        device_id = (row.get("device_id") or "").strip()
        device_name = (row.get("device_name") or "").strip()
        sensor_type = (row.get("sensor_type") or "").strip()
        try:
            x = float(row.get("x", 0))
            y = float(row.get("y", 0))
        except ValueError:
            errors.append({"line": line_no, "error": "좌표가 숫자가 아닙니다."})
            continue
        is_active_raw = (row.get("is_active") or "").strip().lower()
        is_active = is_active_raw in ("1", "true", "on", "yes", "y", "활성")
        unit = (row.get("last_value_unit") or "").strip()

        if not device_id:
            errors.append({"line": line_no, "error": "device_id 누락"})
            continue
        if not device_name:
            errors.append({"line": line_no, "error": "device_name 누락"})
            continue
        if sensor_type not in valid_types:
            errors.append(
                {"line": line_no, "error": f"유효하지 않은 sensor_type: {sensor_type}"}
            )
            continue

        existing = existing_by_id.get(device_id)
        matched = find_containing_geofence(x, y, active_fences)

        if existing:
            if mode == "create":
                skipped += 1
                continue
            # upsert — 변경 내역 추적
            changes = {}
            if existing.device_name != device_name:
                changes["device_name"] = [existing.device_name, device_name]
                existing.device_name = device_name
            if existing.sensor_type != sensor_type:
                changes["sensor_type"] = [existing.sensor_type, sensor_type]
                existing.sensor_type = sensor_type
            if existing.x != x or existing.y != y:
                changes["xy"] = [[existing.x, existing.y], [x, y]]
                existing.x = x
                existing.y = y
            if existing.is_active != is_active:
                changes["is_active"] = [existing.is_active, is_active]
                existing.is_active = is_active
            if unit and existing.last_value_unit != unit:
                changes["last_value_unit"] = [existing.last_value_unit, unit]
                existing.last_value_unit = unit
            if matched and existing.geofence_id != matched.id:
                changes["geofence"] = [
                    existing.geofence.name if existing.geofence else None,
                    matched.name,
                ]
                existing.geofence = matched
            if changes:
                existing.save()
                write_device_history(
                    existing,
                    "csv_import",
                    changes=changes,
                    message=f"CSV upsert (line {line_no})",
                )
                updated += 1
            else:
                skipped += 1
        else:
            d = Device.objects.create(
                device_id=device_id,
                device_name=device_name,
                sensor_type=sensor_type,
                x=x,
                y=y,
                is_active=is_active,
                last_value_unit=unit,
                geofence=matched,
            )
            existing_by_id[device_id] = d
            write_device_history(
                d, "csv_import", message=f"CSV 신규 등록 (line {line_no})"
            )
            created += 1

    return JsonResponse(
        {
            "ok": True,
            "mode": mode,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "error_count": len(errors),
            "errors": errors[:50],
        }
    )


# ═══════════════════════════════════════════════════════════
# 지도 편집 관리 — 피그마 '지도 편집 관리'
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="maps")
def map_edit(request):
    """지도 + 지오펜스 + 장비 통합 편집 화면.
    피그마: 좌측 캔버스 (지도 + 지오펜스 폴리곤 + 장비 마커),
    우측 패널 (지오펜스 목록·등록·수정).
    """
    active_map = (
        MapImage.objects.filter(is_active=True).first() or MapImage.objects.first()
    )
    geofences = list(GeoFence.objects.all().order_by("-created_at"))
    devices_with_geo = list(
        Device.objects.filter(is_active=True).select_related("geofence")
    )
    return render(
        request,
        "backoffice/maps/edit.html",
        {
            "active_map": active_map,
            "geofences": geofences,
            "devices": devices_with_geo,
            "maps": MapImage.objects.all().order_by("-uploaded_at"),
            "zone_types": ZONE_TYPE_CHOICES,
            "risk_levels": RISK_LEVEL_CHOICES,
            "active_menu": "maps",
        },
    )


def _gf_to_dict(g: GeoFence) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "zone_type": g.zone_type,
        "zone_type_display": g.get_zone_type_display(),
        "risk_level": g.risk_level,
        "risk_level_display": g.get_risk_level_display(),
        "description": g.description,
        "polygon": g.polygon,
        "is_active": g.is_active,
        "device_count": g.devices.count(),
        "created_at": g.created_at.strftime("%Y-%m-%d %H:%M") if g.created_at else "-",
    }


@super_admin_required_api(menu_code="maps", action="read")
@require_GET
def geofence_detail_api(request, pk):
    g = get_object_or_404(GeoFence, pk=pk)
    return JsonResponse({"geofence": _gf_to_dict(g)})


@super_admin_required_api(menu_code="maps", action="write")
@require_POST
def geofence_create_api(request):
    form = GeoFenceForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save()
    return JsonResponse({"ok": True, "geofence": _gf_to_dict(g)})


@super_admin_required_api(menu_code="maps", action="write")
@require_POST
def geofence_update_api(request, pk):
    g = get_object_or_404(GeoFence, pk=pk)
    form = GeoFenceForm(_parse_json(request), instance=g)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save()
    return JsonResponse({"ok": True, "geofence": _gf_to_dict(g)})


@super_admin_required_api(menu_code="maps", action="write")
@require_POST
def geofence_delete_api(request, pk):
    g = get_object_or_404(GeoFence, pk=pk)
    # 소속 device 의 geofence FK 는 SET_NULL 로 자동 풀림
    g.delete()
    return JsonResponse({"ok": True})


# ═══════════════════════════════════════════════════════════
# 운영 데이터 관리 (보관 정책)
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="operations")
def retention_list(request):
    rows = list(DataRetentionPolicy.objects.all().order_by("target"))

    # 각 target 별 현재 누적 건수 (대략) 표시
    from devices.models import SensorData
    from workers.models import WorkerLocation
    from alerts.models import Alarm
    from .models import NotificationLog

    counts = {
        "sensor_data": SensorData.objects.count(),
        "worker_location": WorkerLocation.objects.count(),
        "alarms": Alarm.objects.count(),
        "notification_logs": NotificationLog.objects.count(),
        "audit_logs": 0,  # 미구현
    }
    return render(
        request,
        "backoffice/operations/retention_list.html",
        {
            "rows": rows,
            "counts": counts,
            "active_menu": "retention",
        },
    )


def _retention_to_dict(p: DataRetentionPolicy) -> dict:
    return {
        "id": p.id,
        "target": p.target,
        "target_display": p.get_target_display(),
        "retention_days": p.retention_days,
        "is_active": p.is_active,
        "last_run_at": (
            p.last_run_at.strftime("%Y-%m-%d %H:%M") if p.last_run_at else None
        ),
        "last_run_deleted": p.last_run_deleted,
        "description": p.description,
        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else "-",
    }


@super_admin_required_api(menu_code="operations", action="read")
@require_GET
def retention_detail_api(request, pk):
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    return JsonResponse({"retention": _retention_to_dict(p)})


@super_admin_required_api(menu_code="operations", action="write")
@require_POST
def retention_update_api(request, pk):
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    form = DataRetentionForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "retention": _retention_to_dict(p)})


@super_admin_required_api(menu_code="operations", action="write")
@require_POST
def retention_run_now_api(request, pk):
    """단건 정책 즉시 실행 — 백그라운드 큐 없이 동기로 처리.
    레코드 수가 많으면 timeout 가능성 있어 v6 에서 큐로 분리 권장.
    """
    from datetime import timedelta as _td
    from .management.commands.cleanup_data import _resolve_qs

    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    if not p.is_active:
        return JsonResponse(
            {"ok": False, "error": "비활성 정책은 실행할 수 없습니다."}, status=400
        )

    cutoff = timezone.now() - _td(days=p.retention_days)
    qs = _resolve_qs(p.target, cutoff)
    if qs is None:
        return JsonResponse(
            {"ok": False, "error": "대상 모델 매핑이 없습니다."}, status=400
        )

    deleted, _ = qs.delete()
    p.last_run_at = timezone.now()
    p.last_run_deleted = deleted
    p.save(update_fields=["last_run_at", "last_run_deleted"])
    return JsonResponse(
        {"ok": True, "deleted": deleted, "retention": _retention_to_dict(p)}
    )


# ═══════════════════════════════════════════════════════════
# 공지사항 관리
# ═══════════════════════════════════════════════════════════

NOTICE_PAGE_SIZE = 20


@super_admin_required(menu_code="notices")
def notice_list(request):
    qs = Notice.objects.all()

    q_keyword = request.GET.get("keyword", "").strip()
    q_category = request.GET.get("category", "").strip()
    q_published = request.GET.get("published", "").strip()

    if q_keyword:
        qs = qs.filter(Q(title__icontains=q_keyword) | Q(content__icontains=q_keyword))
    if q_category:
        qs = qs.filter(category=q_category)
    if q_published == "1":
        qs = qs.filter(is_published=True)
    elif q_published == "0":
        qs = qs.filter(is_published=False)

    qs = qs.order_by("-is_pinned", "-created_at")
    total = qs.count()

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * NOTICE_PAGE_SIZE
    rows = list(qs[start : start + NOTICE_PAGE_SIZE])
    last_page = max(1, (total + NOTICE_PAGE_SIZE - 1) // NOTICE_PAGE_SIZE)

    return render(
        request,
        "backoffice/notices/list.html",
        {
            "rows": rows,
            "total": total,
            "page": page,
            "last_page": last_page,
            "page_start": start + 1 if total else 0,
            "page_end": min(start + NOTICE_PAGE_SIZE, total),
            "page_range": range(max(1, page - 4), min(last_page, page + 4) + 1),
            "categories": NOTICE_CATEGORY_CHOICES,
            "q": {
                "keyword": q_keyword,
                "category": q_category,
                "published": q_published,
            },
            "active_menu": "notices",
        },
    )


def _notice_to_dict(n: Notice) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "category": n.category,
        "category_display": n.get_category_display(),
        "content": n.content,
        "is_pinned": n.is_pinned,
        "is_published": n.is_published,
        "published_from": (
            n.published_from.strftime("%Y-%m-%dT%H:%M") if n.published_from else None
        ),
        "published_to": (
            n.published_to.strftime("%Y-%m-%dT%H:%M") if n.published_to else None
        ),
        "view_count": n.view_count,
        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "-",
        "created_by_name": n.created_by.first_name if n.created_by else "-",
    }


@super_admin_required_api(menu_code="notices", action="read")
@require_GET
def notice_detail_api(request, pk):
    n = get_object_or_404(Notice, pk=pk)
    return JsonResponse({"notice": _notice_to_dict(n)})


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_create_api(request):
    form = NoticeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    n = form.save(by=request.user)

    # v5 — 게시 + send_notify 옵션 시 즉시 발송
    payload = _parse_json(request)
    if payload.get("send_notify") and n.is_published:
        from .notification_dispatcher import dispatch_for_notice

        try:
            dispatched = dispatch_for_notice(n)
            return JsonResponse(
                {"ok": True, "notice": _notice_to_dict(n), "dispatched": dispatched}
            )
        except Exception as e:
            # 알림 발송 실패는 공지 등록 자체엔 영향 없음
            return JsonResponse(
                {"ok": True, "notice": _notice_to_dict(n), "notify_error": str(e)}
            )

    return JsonResponse({"ok": True, "notice": _notice_to_dict(n)})


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_dispatch_api(request, pk):
    """기존 공지를 수동으로 사용자에게 알림 발송."""
    n = get_object_or_404(Notice, pk=pk)
    if not n.is_published:
        return JsonResponse(
            {"ok": False, "error": "미게시 공지는 발송할 수 없습니다."}, status=400
        )
    from .notification_dispatcher import dispatch_for_notice

    channels = _parse_json(request).get("channels") or ["app", "realtime"]
    dispatched = dispatch_for_notice(n, channels=channels)
    return JsonResponse({"ok": True, "dispatched": dispatched})


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_update_api(request, pk):
    n = get_object_or_404(Notice, pk=pk)
    form = NoticeForm(_parse_json(request), instance=n)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    n = form.save(by=request.user)
    return JsonResponse({"ok": True, "notice": _notice_to_dict(n)})


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_bulk_delete_api(request):
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Notice.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_published"))
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Notice.objects.filter(id__in=ids).update(is_published=target)
    return JsonResponse({"ok": True, "updated": n})


# ═══════════════════════════════════════════════════════════
# v6 — Audit Log 조회 페이지 + Device History API
# ═══════════════════════════════════════════════════════════

AUDIT_PAGE_SIZE = 30


@super_admin_required(menu_code="operations")
def audit_log_list(request):
    from .models import AuditLog, AUDIT_ACTION_CHOICES

    qs = AuditLog.objects.select_related("actor").all()

    q_action = request.GET.get("action", "").strip()
    q_target = request.GET.get("target_model", "").strip()
    q_keyword = request.GET.get("keyword", "").strip()
    q_from = request.GET.get("from", "").strip()
    q_to = request.GET.get("to", "").strip()

    if q_action:
        qs = qs.filter(action=q_action)
    if q_target:
        qs = qs.filter(target_model=q_target)
    if q_keyword:
        qs = qs.filter(
            Q(actor_username_snapshot__icontains=q_keyword)
            | Q(target_repr__icontains=q_keyword)
            | Q(extra_message__icontains=q_keyword)
            | Q(request_path__icontains=q_keyword)
        )
    if q_from:
        try:
            dt = datetime.strptime(q_from, "%Y-%m-%d")
            qs = qs.filter(created_at__gte=timezone.make_aware(dt))
        except ValueError:
            pass
    if q_to:
        try:
            dt = datetime.strptime(q_to, "%Y-%m-%d") + timedelta(days=1)
            qs = qs.filter(created_at__lt=timezone.make_aware(dt))
        except ValueError:
            pass

    qs = qs.order_by("-created_at")
    total = qs.count()

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * AUDIT_PAGE_SIZE
    rows = list(qs[start : start + AUDIT_PAGE_SIZE])
    last_page = max(1, (total + AUDIT_PAGE_SIZE - 1) // AUDIT_PAGE_SIZE)

    # 추적 모델 목록 (필터용)
    target_models = list(
        AuditLog.objects.values_list("target_model", flat=True)
        .distinct()
        .order_by("target_model")
    )

    return render(
        request,
        "backoffice/audit/log_list.html",
        {
            "rows": rows,
            "total": total,
            "page": page,
            "last_page": last_page,
            "page_start": start + 1 if total else 0,
            "page_end": min(start + AUDIT_PAGE_SIZE, total),
            "page_range": range(max(1, page - 4), min(last_page, page + 4) + 1),
            "actions": AUDIT_ACTION_CHOICES,
            "target_models": target_models,
            "q": {
                "action": q_action,
                "target_model": q_target,
                "keyword": q_keyword,
                "from": q_from,
                "to": q_to,
            },
            "active_menu": "audit",
        },
    )


@super_admin_required_api(menu_code="devices", action="read")
@require_GET
def device_history_api(request, pk):
    """단일 장비의 변경 이력. 모달 표시용."""
    from .models import DeviceHistory

    d = get_object_or_404(Device, pk=pk)
    history = DeviceHistory.objects.filter(device_id_snapshot=d.device_id).order_by(
        "-created_at"
    )[:50]
    return JsonResponse(
        {
            "device": {
                "id": d.id,
                "device_id": d.device_id,
                "device_name": d.device_name,
            },
            "history": [
                {
                    "id": h.id,
                    "action": h.action,
                    "action_display": h.get_action_display(),
                    "actor": h.actor_username_snapshot or "-",
                    "changes": h.changes,
                    "message": h.extra_message,
                    "created_at": h.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for h in history
            ],
        }
    )
