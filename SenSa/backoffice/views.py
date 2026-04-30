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
    # parent가 없는 최상위 노드(회사 루트)를 가져옴. 트리 구조에서 가장 상위 조직.
    departments = []
    if company:
        departments = list(
            company.children.exclude(is_unassigned_bucket=True).order_by("sort_order")
        )
        # "조직 없음" 가상 버킷을 제외한 실제 부서 목록을 sort_order 순으로 가져옴.
        unassigned = company.children.filter(is_unassigned_bucket=True).first()
        # "조직 없음" 가상 버킷은 목록 맨 아래에 따로 추가해 항상 마지막에 표시.
        if unassigned:
            departments.append(unassigned)

    ctx = {
        "company": company,
        "departments": departments,
    }
    return render(request, "backoffice/organizations/manage.html", ctx)
    # 회사 정보와 부서 목록을 템플릿에 넘겨 조직 트리 초기 화면을 렌더링.


def _org_to_dict(org: Organization) -> dict:
    # Organization 모델 인스턴스를 JSON 직렬화 가능한 dict로 변환하는 내부 헬퍼.
    # API 응답에서 조직 데이터를 일관된 형태로 내보낼 때 재사용.
    return {
        "id": org.id,
        "name": org.name,
        "code": org.code,
        "parent_id": org.parent_id,
        # 부모 조직 ID — 트리 구조에서 이 부서가 어느 상위 조직에 속하는지 나타냄.
        "description": org.description,
        "leader_id": org.leader_id,
        "leader_name": org.leader.first_name if org.leader else None,
        # 조직장이 지정된 경우 이름을, 없으면 None 반환.
        "is_unassigned_bucket": org.is_unassigned_bucket,
        # True이면 "조직 없음" 가상 버킷 — 삭제·수정 불가 플래그로 활용됨.
        "is_root": org.is_root,
        # True이면 회사(루트) 노드 — 삭제 불가.
        "member_count": org.member_count,
        "updated_at": (
            org.updated_at.strftime("%Y-%m-%d %H:%M") if org.updated_at else "-"
        ),
        "updated_by_name": org.updated_by.first_name if org.updated_by else "-",
        # 최종 수정자 이름. 수정 이력이 없으면 "-" 표시.
    }


@super_admin_required_api
@require_GET
def organization_detail_api(request, pk):
    # 부서 ID(pk)에 해당하는 조직 상세 정보와 소속 구성원 목록을 JSON으로 반환.
    # 프런트엔드에서 부서 클릭 시 우측 패널을 AJAX로 채울 때 사용.
    org = get_object_or_404(Organization, pk=pk)
    members = org.users.select_related("position_obj").order_by("-id")
    # 이 부서에 소속된 사용자 목록을 직위(position_obj) JOIN으로 가져옴. N+1 방지.
    members_data = [
        {
            "id": u.id,
            "name": u.first_name,
            "username": u.username,
            "position": u.display_position,
            "account_status": u.account_status,
            "account_status_display": u.account_status_display,
            "is_leader": (u.id == org.leader_id),
            # 해당 사용자가 이 부서의 조직장인지 여부를 bool로 포함.
        }
        for u in members
    ]

    return JsonResponse(
        {
            "organization": _org_to_dict(org),
            "members": members_data,
        }
    )
    # 조직 정보와 구성원 목록을 하나의 JSON 응답으로 묶어 반환.


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def organization_create_api(request):
    # 새 부서를 생성하는 API. POST body의 JSON 데이터를 OrganizationForm으로 검증 후 저장.
    form = OrganizationForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
        # 폼 유효성 검사 실패 시 필드별 에러 메시지를 400으로 반환.
    org = form.save(by=request.user)
    # 현재 요청자(request.user)를 updated_by로 기록하며 저장.
    return JsonResponse({"ok": True, "organization": _org_to_dict(org)})
    # 생성 성공 시 새 조직의 dict를 포함한 ok 응답 반환.


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def organization_update_api(request, pk):
    # 기존 부서 정보를 수정하는 API. "조직 없음" 가상 버킷은 수정 불가 처리.
    org = get_object_or_404(Organization, pk=pk)
    if org.is_unassigned_bucket:
        return JsonResponse(
            {"ok": False, "error": '"조직 없음" 가상 부서는 수정할 수 없습니다.'},
            status=400,
        )
        # "조직 없음"은 시스템이 자동 관리하는 가상 부서 — 수동 수정 차단.
    form = OrganizationForm(_parse_json(request), instance=org)
    # 기존 인스턴스를 넘겨 UPDATE 쿼리가 실행되도록 함(새 INSERT 방지).
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    org = form.save(by=request.user)
    return JsonResponse({"ok": True, "organization": _org_to_dict(org)})
    # 수정 완료 후 갱신된 조직 정보를 반환.


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
        # "조직 없음"은 미배정 사용자의 보관함 역할 — 삭제하면 갈 곳 없는 사용자가 생기므로 차단.
    if org.is_root:
        return JsonResponse(
            {"ok": False, "error": "회사(루트) 노드는 삭제할 수 없습니다."},
            status=400,
        )
        # 루트(회사) 노드를 삭제하면 전체 조직 트리가 무너지므로 차단.
    # 소속 사용자 → 조직 없음 으로 이동
    company = org.parent
    # 이 부서의 상위 회사를 찾아 "조직 없음" 버킷을 탐색.
    bucket = (
        company.children.filter(is_unassigned_bucket=True).first() if company else None
    )
    if bucket:
        org.users.update(organization=bucket)
        # 부서가 삭제되기 전에 소속 사용자 전원을 "조직 없음" 버킷으로 일괄 이동.

    org.delete()
    return JsonResponse({"ok": True})
    # 부서 삭제 완료. 사용자는 이미 재배정된 상태.


@super_admin_required_api
@require_POST
def organization_assign_members_api(request, pk):
    """피그마 '구성원 추가' — 다른 부서 사용자를 이 부서로 옮김(또는 겸직).
    body: {"user_ids": [...], "keep_previous": false}
    keep_previous 는 v1 에서는 무시 (겸직 미지원, v2)
    """
    # 선택한 사용자들을 이 부서(pk)로 소속 이동시키는 API.
    org = get_object_or_404(Organization, pk=pk)
    data = _parse_json(request)
    user_ids = data.get("user_ids") or []
    if not user_ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
        # 대상 user_ids가 비어있으면 400 에러 반환.
    n = User.objects.filter(id__in=user_ids).update(
        organization=org,
        department=org.name,
    )
    # 선택된 사용자들의 organization FK와 department 문자열을 일괄 업데이트.
    return JsonResponse({"ok": True, "assigned": n})
    # 실제로 업데이트된 사용자 수를 반환.


@super_admin_required_api
@require_POST
def organization_remove_members_api(request, pk):
    """피그마 '소속 제외' — 선택된 사용자를 '조직 없음' 으로."""
    # 이 부서에서 선택된 사용자를 제외하고 "조직 없음" 버킷으로 이동시키는 API.
    org = get_object_or_404(Organization, pk=pk)
    user_ids = _parse_json(request).get("user_ids") or []
    if not user_ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    company = org.parent if not org.is_root else org
    # 루트(회사)면 자기 자신을, 아니면 상위 회사를 참조하여 "조직 없음" 버킷을 탐색.
    bucket = (
        company.children.filter(is_unassigned_bucket=True).first() if company else None
    )
    if not bucket:
        return JsonResponse(
            {"ok": False, "error": '"조직 없음" 가상 부서를 찾을 수 없습니다.'},
            status=500,
        )
        # "조직 없음" 버킷이 없으면 이동 불가 — 서버 설정 이상으로 500 반환.
    n = User.objects.filter(id__in=user_ids, organization=org).update(
        organization=bucket,
        department=bucket.name,
    )
    # 이 부서 소속인 사용자만 선별하여 "조직 없음"으로 이동. 다른 부서 소속은 건드리지 않음.
    return JsonResponse({"ok": True, "removed": n})
    # 실제 이동된 사용자 수를 반환.


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def organization_set_leader_api(request, pk):
    """조직장 임명. body: {"user_id": ...}
    피그마: 다중 선택 시 비활성, 단건만 가능.
    """
    # 이 부서의 조직장을 지정하는 API. 반드시 해당 부서 소속 사용자여야만 임명 가능.
    org = get_object_or_404(Organization, pk=pk)
    user_id = _parse_json(request).get("user_id")
    if not user_id:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    try:
        u = User.objects.get(pk=user_id, organization=org)
        # 부서 소속 여부를 동시에 검증 — 다른 부서 사람을 조직장으로 임명하는 실수 방지.
    except User.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": "해당 부서 소속 사용자만 조직장 지정 가능합니다."},
            status=400,
        )
    org.leader = u
    org.updated_by = request.user
    org.save(update_fields=["leader", "updated_by", "updated_at"])
    # 변경된 필드만 지정해 불필요한 전체 UPDATE 방지.
    return JsonResponse({"ok": True})
    # 조직장 임명 성공 응답.


@super_admin_required_api
@require_GET
def organization_member_picker_api(request):
    """구성원 선택 팝업 — 부서별 구성원 목록 제공.
    GET ?org_id=<id> → 해당 부서 구성원 (이미 그 부서면 선택 불가)
    GET (org_id 없음) → 회사 전체 구성원
    """
    # "구성원 추가" 팝업에서 사용자 목록을 제공. org_id를 넘기면 이미 그 부서 소속인지 표시.
    org_id = request.GET.get("org_id")
    qs = User.objects.select_related("organization", "position_obj").order_by(
        "first_name"
    )
    # 전체 사용자를 이름 오름차순으로 가져오며, 조직·직위를 JOIN으로 함께 로드.
    target_org_id = None
    if org_id:
        try:
            target_org_id = int(org_id)
        except ValueError:
            target_org_id = None
            # org_id가 숫자가 아니면 무시 — 잘못된 파라미터에 대해 500 대신 전체 목록 반환.

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
            # 이미 대상 부서 소속이면 True — 프런트에서 체크박스 비활성화에 활용.
        }
        for u in qs
    ]
    return JsonResponse({"users": payload})
    # 전체 사용자 목록과 대상 부서 소속 여부를 함께 반환.


# ═══════════════════════════════════════════════════════════
# 직위 관리 — 페이지 + API
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="users")
def position_list(request):
    # 직위 목록 페이지. GET ?q= 파라미터로 이름 검색 가능.
    q = request.GET.get("q", "").strip()
    qs = Position.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
        # 검색어가 있으면 직위명에 포함된 것만 필터링 (대소문자 무시).
    qs = qs.order_by("sort_order", "name")
    # sort_order 기본 정렬, 같은 순서면 이름 알파벳순으로 보조 정렬.
    return render(
        request,
        "backoffice/positions/list.html",
        {
            "rows": list(qs),
            "q": q,
        },
    )
    # 직위 목록과 현재 검색어를 템플릿에 넘겨 렌더링.


def _position_to_dict(p: Position) -> dict:
    # Position 모델 인스턴스를 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    # 직위 관련 API 응답에서 일관된 형태로 데이터를 내보낼 때 재사용.
    return {
        "id": p.id,
        "name": p.name,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "description": p.description,
        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else "-",
        # 수정 이력이 없으면 "-" 표시.
    }


@super_admin_required_api(menu_code="users", action="read")
@require_GET
def position_detail_api(request, pk):
    # 특정 직위 1건의 상세 정보를 JSON으로 반환. 수정 모달 팝업 데이터 로드에 사용.
    p = get_object_or_404(Position, pk=pk)
    return JsonResponse({"position": _position_to_dict(p)})
    # 해당 직위 데이터를 dict로 변환하여 반환.


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def position_create_api(request):
    # 새 직위를 생성하는 API. PositionForm으로 유효성 검사 후 저장.
    form = PositionForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "position": _position_to_dict(p)})
    # 생성된 직위 정보를 응답으로 반환.


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def position_update_api(request, pk):
    # 기존 직위를 수정하는 API. 기존 인스턴스를 폼에 넘겨 UPDATE 쿼리 실행.
    p = get_object_or_404(Position, pk=pk)
    form = PositionForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)},
            status=400,
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "position": _position_to_dict(p)})
    # 수정된 직위 정보를 응답으로 반환.


@super_admin_required_api(menu_code="users", action="write")
@require_POST
def position_bulk_delete_api(request):
    # 체크박스로 선택한 직위 여러 건을 한 번에 삭제하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Position.objects.filter(id__in=ids).delete()
    # 선택된 ID 목록에 해당하는 직위를 DB에서 일괄 삭제.
    return JsonResponse({"ok": True, "deleted": deleted})
    # 실제로 삭제된 건수를 응답으로 반환.


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
    # 코드 그룹 전체를 정렬 순서대로 가져와 좌측 트리 패널 초기 데이터로 사용.
    groups = list(CodeGroup.objects.all().order_by("sort_order", "code"))
    # sort_order 우선, 같은 순서면 코드 알파벳순으로 정렬.
    return render(
        request,
        "backoffice/codes/manage.html",
        {
            "groups": groups,
            "active_menu": "codes",
        },
    )
    # 코드 그룹 목록을 템플릿에 넘겨 2-패널 관리 화면을 렌더링.


def _code_group_to_dict(g: CodeGroup) -> dict:
    # CodeGroup 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": g.id,
        "code": g.code,
        "name": g.name,
        "description": g.description,
        "sort_order": g.sort_order,
        "is_active": g.is_active,
        "is_system": g.is_system,
        # True이면 시스템 코드 그룹 — 삭제 불가 플래그로 활용됨.
        "code_count": g.code_count,
        # 이 그룹에 속한 코드 수 (모델 프로퍼티로 계산).
        "updated_at": g.updated_at.strftime("%Y-%m-%d %H:%M") if g.updated_at else "-",
        "updated_by_name": g.updated_by.first_name if g.updated_by else "-",
    }


def _code_to_dict(c: Code) -> dict:
    # Code 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": c.id,
        "group_id": c.group_id,
        # 이 코드가 속한 그룹의 FK.
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
    # 코드 그룹 1건 상세와 해당 그룹의 코드 목록을 반환. 우측 패널 AJAX 로드에 사용.
    g = get_object_or_404(CodeGroup, pk=pk)
    codes = [_code_to_dict(c) for c in g.codes.order_by("sort_order", "code")]
    # 그룹에 속한 코드를 sort_order → code 순으로 정렬하여 포함.
    return JsonResponse({"group": _code_group_to_dict(g), "codes": codes})
    # 그룹 정보와 코드 목록을 묶어 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_group_create_api(request):
    # 새 코드 그룹을 생성하는 API.
    form = CodeGroupForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save(by=request.user)
    return JsonResponse({"ok": True, "group": _code_group_to_dict(g)})
    # 생성된 그룹 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_group_update_api(request, pk):
    # 기존 코드 그룹의 정보를 수정하는 API.
    g = get_object_or_404(CodeGroup, pk=pk)
    form = CodeGroupForm(_parse_json(request), instance=g)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save(by=request.user)
    return JsonResponse({"ok": True, "group": _code_group_to_dict(g)})
    # 수정된 그룹 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_group_delete_api(request, pk):
    # 코드 그룹을 삭제하는 API. 시스템 코드 그룹은 삭제 불가 처리.
    g = get_object_or_404(CodeGroup, pk=pk)
    if g.is_system:
        return JsonResponse(
            {"ok": False, "error": "시스템 코드 그룹은 삭제할 수 없습니다."},
            status=400,
        )
        # is_system=True인 그룹은 시스템이 의존하는 필수 코드 — 삭제 차단.
    g.delete()
    return JsonResponse({"ok": True})
    # 삭제 완료 응답.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_create_api(request):
    # 특정 그룹에 속하는 새 코드 항목을 생성하는 API.
    form = CodeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "code": _code_to_dict(c)})
    # 생성된 코드 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_update_api(request, pk):
    # 기존 코드 항목을 수정하는 API.
    c = get_object_or_404(Code, pk=pk)
    form = CodeForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "code": _code_to_dict(c)})
    # 수정된 코드 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_bulk_delete_api(request):
    # 선택된 코드 항목 여러 건을 일괄 삭제하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Code.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
    # 삭제된 건수를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def code_bulk_toggle_api(request):
    """is_active 일괄 변경. body: {"ids": [...], "is_active": false}"""
    # 선택된 코드 항목들의 활성/비활성 상태를 일괄로 변경하는 API.
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    # 요청의 is_active 값을 bool로 변환하여 목표 상태 결정.
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Code.objects.filter(id__in=ids).update(is_active=target)
    # 선택된 코드들의 is_active 필드를 한 번의 쿼리로 일괄 업데이트.
    return JsonResponse({"ok": True, "updated": n})
    # 업데이트된 건수를 응답으로 반환.


# ───────────────── 위험 유형 ─────────────────


@super_admin_required(menu_code="references")
def risk_manage(request):
    # 위험 유형 관리 페이지. 좌측에 위험 분류(RiskCategory) 목록, 우측에 유형 상세 패널 구성.
    cats = list(RiskCategory.objects.all().order_by("sort_order", "code"))
    # 위험 분류 전체를 sort_order → code 순으로 정렬하여 좌측 목록에 표시.
    return render(
        request,
        "backoffice/risks/manage.html",
        {
            "categories": cats,
            "active_menu": "risks",
        },
    )
    # 분류 목록을 템플릿에 넘겨 위험 유형 관리 화면을 렌더링.


def _risk_cat_to_dict(c: RiskCategory) -> dict:
    # RiskCategory 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "description": c.description,
        "applies_to": c.applies_to,
        # 이 분류가 적용되는 도메인 (예: "realtime,alarm") — 콤마 구분 문자열.
        "applies_to_list": c.applies_to_list,
        # applies_to를 리스트로 파싱한 프로퍼티.
        "sort_order": c.sort_order,
        "is_active": c.is_active,
        "is_system": c.is_system,
        # True이면 시스템 분류 — 삭제 차단.
        "type_count": c.type_count,
        # 이 분류에 속한 위험 유형 수.
        "updated_at": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "-",
        "updated_by_name": c.updated_by.first_name if c.updated_by else "-",
    }


def _risk_type_to_dict(t: RiskType) -> dict:
    # RiskType 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": t.id,
        "category_id": t.category_id,
        # 이 유형이 속하는 위험 분류의 FK.
        "code": t.code,
        "name": t.name,
        "description": t.description,
        "show_on_map": t.show_on_map,
        # True이면 지도 위에 위험 마커로 표시.
        "sort_order": t.sort_order,
        "is_active": t.is_active,
        "updated_at": t.updated_at.strftime("%Y-%m-%d %H:%M") if t.updated_at else "-",
    }


@super_admin_required_api(menu_code="references", action="read")
@require_GET
def risk_cat_detail_api(request, pk):
    # 위험 분류 1건의 상세 정보와 해당 분류에 속한 위험 유형 목록을 반환.
    c = get_object_or_404(RiskCategory, pk=pk)
    types = [_risk_type_to_dict(t) for t in c.types.order_by("sort_order", "code")]
    # 소속 유형을 sort_order → code 순으로 정렬하여 포함.
    return JsonResponse({"category": _risk_cat_to_dict(c), "types": types})
    # 분류 정보와 유형 목록을 묶어 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_cat_create_api(request):
    # 새 위험 분류를 생성하는 API.
    form = RiskCategoryForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _risk_cat_to_dict(c)})
    # 생성된 분류 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_cat_update_api(request, pk):
    # 기존 위험 분류를 수정하는 API.
    c = get_object_or_404(RiskCategory, pk=pk)
    form = RiskCategoryForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _risk_cat_to_dict(c)})
    # 수정된 분류 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_cat_delete_api(request, pk):
    # 위험 분류를 삭제하는 API. 시스템 분류는 삭제 불가 처리.
    c = get_object_or_404(RiskCategory, pk=pk)
    if c.is_system:
        return JsonResponse(
            {"ok": False, "error": "시스템 분류는 삭제할 수 없습니다."}, status=400
        )
        # 시스템이 의존하는 필수 분류는 삭제 차단.
    c.delete()
    return JsonResponse({"ok": True})
    # 삭제 완료 응답.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_type_create_api(request):
    # 특정 위험 분류에 속하는 새 위험 유형을 생성하는 API.
    form = RiskTypeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "type": _risk_type_to_dict(t)})
    # 생성된 위험 유형 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_type_update_api(request, pk):
    # 기존 위험 유형을 수정하는 API.
    t = get_object_or_404(RiskType, pk=pk)
    form = RiskTypeForm(_parse_json(request), instance=t)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "type": _risk_type_to_dict(t)})
    # 수정된 위험 유형 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def risk_type_bulk_delete_api(request):
    # 선택된 위험 유형 여러 건을 일괄 삭제하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = RiskType.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
    # 삭제된 건수를 응답으로 반환.


# ───────────────── 위험 기준 (알람 단계) ─────────────────


@super_admin_required(menu_code="references")
def alarm_level_list(request):
    # 알람 단계(위험 기준) 목록 페이지. 우선순위 → 코드 순으로 정렬하여 표시.
    rows = list(AlarmLevel.objects.all().order_by("priority", "code"))
    # priority가 낮을수록 심각도가 높아지는 구조 (예: 1=위험, 2=경고).
    return render(
        request,
        "backoffice/alarm_levels/list.html",
        {
            "rows": rows,
            "active_menu": "alarm_levels",
        },
    )
    # 알람 단계 목록을 템플릿에 넘겨 렌더링.


def _alarm_to_dict(a: AlarmLevel) -> dict:
    # AlarmLevel 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": a.id,
        "code": a.code,
        "name": a.name,
        "color": a.color,
        # 알람 표시 색상 코드 (예: "red", "orange").
        "color_display": a.get_color_display(),
        # choices에 정의된 색상 레이블 (예: "빨강").
        "intensity": a.intensity,
        # 알람 강도 수치 — UI 시각화에 활용.
        "intensity_display": a.get_intensity_display(),
        "priority": a.priority,
        # 숫자가 작을수록 높은 우선순위 (더 심각한 알람).
        "description": a.description,
        "is_active": a.is_active,
        "is_system": a.is_system,
        # True이면 시스템 기본 단계 — 삭제 차단.
        "updated_at": a.updated_at.strftime("%Y-%m-%d %H:%M") if a.updated_at else "-",
    }


@super_admin_required_api(menu_code="references", action="read")
@require_GET
def alarm_level_detail_api(request, pk):
    # 특정 알람 단계 1건의 상세 정보를 JSON으로 반환. 수정 모달 데이터 로드에 사용.
    a = get_object_or_404(AlarmLevel, pk=pk)
    return JsonResponse({"alarm_level": _alarm_to_dict(a)})
    # 알람 단계 데이터를 dict로 변환하여 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def alarm_level_create_api(request):
    # 새 알람 단계를 생성하는 API.
    form = AlarmLevelForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    a = form.save(by=request.user)
    return JsonResponse({"ok": True, "alarm_level": _alarm_to_dict(a)})
    # 생성된 알람 단계 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def alarm_level_update_api(request, pk):
    # 기존 알람 단계를 수정하는 API.
    a = get_object_or_404(AlarmLevel, pk=pk)
    form = AlarmLevelForm(_parse_json(request), instance=a)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    a = form.save(by=request.user)
    return JsonResponse({"ok": True, "alarm_level": _alarm_to_dict(a)})
    # 수정된 알람 단계 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def alarm_level_bulk_delete_api(request):
    # 선택된 알람 단계 여러 건을 일괄 삭제하는 API. 시스템 단계는 보호.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    # 시스템 레벨 보호
    sys_ids = list(
        AlarmLevel.objects.filter(id__in=ids, is_system=True).values_list(
            "id", flat=True
        )
    )
    # 선택 목록 중 is_system=True인 항목 ID를 미리 수집하여 차단 여부 검사.
    if sys_ids:
        return JsonResponse(
            {
                "ok": False,
                "error": f"시스템 단계 {len(sys_ids)}개는 삭제할 수 없습니다.",
            },
            status=400,
        )
        # 시스템 단계가 하나라도 포함되면 전체 삭제 요청을 거부.
    deleted, _ = AlarmLevel.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
    # 삭제된 건수를 응답으로 반환.


# ───────────────── 임계치 기준 ─────────────────


@super_admin_required(menu_code="references")
def threshold_manage(request):
    # 임계치 기준 관리 페이지. 좌측 분류(ThresholdCategory) 목록, 우측 임계치 패널 구성.
    cats = list(ThresholdCategory.objects.all().order_by("sort_order", "code"))
    # 임계치 분류 전체를 sort_order → code 순으로 정렬하여 좌측 목록에 표시.
    return render(
        request,
        "backoffice/thresholds/manage.html",
        {
            "categories": cats,
            "active_menu": "thresholds",
        },
    )
    # 분류 목록을 템플릿에 넘겨 임계치 관리 화면을 렌더링.


def _th_cat_to_dict(c: ThresholdCategory) -> dict:
    # ThresholdCategory 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "description": c.description,
        "applies_to": c.applies_to,
        # 이 임계치 분류가 적용되는 도메인 (예: "realtime,alarm").
        "applies_to_list": c.applies_to_list,
        # applies_to를 리스트로 파싱한 프로퍼티.
        "sort_order": c.sort_order,
        "is_active": c.is_active,
        "is_system": c.is_system,
        # True이면 시스템 분류 — 삭제 불가.
        "threshold_count": c.threshold_count,
        # 이 분류에 속한 임계치 항목 수.
        "updated_at": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "-",
        "updated_by_name": c.updated_by.first_name if c.updated_by else "-",
    }


def _th_to_dict(t: Threshold) -> dict:
    # Threshold 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": t.id,
        "category_id": t.category_id,
        # 이 임계치가 속하는 분류의 FK.
        "item_code": t.item_code,
        # 센서 항목 코드 (예: "CO", "TEMP") — FastAPI 조회 키로 사용됨.
        "item_name": t.item_name,
        "unit": t.unit,
        # 측정 단위 (예: "ppm", "°C").
        "operator": t.operator,
        # 비교 연산자 코드 (예: "gte" = 이상, "lte" = 이하).
        "operator_display": t.get_operator_display(),
        "caution_value": t.caution_value,
        # 주의 임계값 — 이 값을 초과하면 경고 알람 발생.
        "danger_value": t.danger_value,
        # 위험 임계값 — 이 값을 초과하면 위험 알람 발생.
        "is_active": t.is_active,
        "applies_to": t.applies_to,
        "applies_to_list": t.applies_to_list,
        "description": t.description,
        "updated_at": t.updated_at.strftime("%Y-%m-%d %H:%M") if t.updated_at else "-",
    }


@super_admin_required_api(menu_code="references", action="read")
@require_GET
def threshold_cat_detail_api(request, pk):
    # 임계치 분류 1건의 상세 정보와 해당 분류의 임계치 항목 목록을 반환.
    c = get_object_or_404(ThresholdCategory, pk=pk)
    items = [_th_to_dict(t) for t in c.thresholds.order_by("item_code")]
    # 임계치 항목을 item_code 알파벳순으로 정렬하여 포함.
    return JsonResponse({"category": _th_cat_to_dict(c), "thresholds": items})
    # 분류 정보와 임계치 목록을 묶어 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_cat_create_api(request):
    # 새 임계치 분류를 생성하는 API.
    form = ThresholdCategoryForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _th_cat_to_dict(c)})
    # 생성된 임계치 분류 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_cat_update_api(request, pk):
    # 기존 임계치 분류를 수정하는 API.
    c = get_object_or_404(ThresholdCategory, pk=pk)
    form = ThresholdCategoryForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    c = form.save(by=request.user)
    return JsonResponse({"ok": True, "category": _th_cat_to_dict(c)})
    # 수정된 임계치 분류 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_create_api(request):
    # 새 임계치 항목을 생성하는 API. 주의값·위험값·연산자 등을 ThresholdForm으로 검증.
    form = ThresholdForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "threshold": _th_to_dict(t)})
    # 생성된 임계치 항목 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_update_api(request, pk):
    # 기존 임계치 항목을 수정하는 API.
    t = get_object_or_404(Threshold, pk=pk)
    form = ThresholdForm(_parse_json(request), instance=t)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    t = form.save(by=request.user)
    return JsonResponse({"ok": True, "threshold": _th_to_dict(t)})
    # 수정된 임계치 항목 정보를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_bulk_delete_api(request):
    # 선택된 임계치 항목 여러 건을 일괄 삭제하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Threshold.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
    # 삭제된 건수를 응답으로 반환.


@super_admin_required_api(menu_code="references", action="write")
@require_POST
def threshold_bulk_toggle_api(request):
    # 선택된 임계치 항목들의 활성/비활성 상태를 일괄 변경하는 API.
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    # 목표 활성 상태를 bool로 변환.
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Threshold.objects.filter(id__in=ids).update(is_active=target)
    # 선택된 임계치들의 is_active 필드를 한 번의 쿼리로 일괄 업데이트.
    return JsonResponse({"ok": True, "updated": n})
    # 업데이트된 건수를 응답으로 반환.


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
    # CSRF 검증을 면제(@csrf_exempt) — FastAPI가 내부 API키로 호출하므로 세션 쿠키가 없음.
    cats = ThresholdCategory.objects.filter(is_active=True).prefetch_related(
        "thresholds"
    )
    # 활성 분류만 가져오며, 소속 임계치를 prefetch로 함께 로드하여 N+1 방지.
    payload = {"categories": {}, "flat": {}}
    # categories: 분류 코드 → 분류 객체 dict / flat: "분류코드.항목코드" → 항목 dict (빠른 단건 조회용).
    for cat in cats:
        cat_obj = {
            "code": cat.code,
            "name": cat.name,
            "applies_to": cat.applies_to_list,
            "thresholds": [],
        }
        for t in cat.thresholds.filter(is_active=True):
            # 비활성 임계치는 FastAPI에 전달하지 않음.
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
            # "TH_GAS.CO" 형태의 복합 키로 flat에 저장하여 generators.py에서 O(1) 조회 가능.

        payload["categories"][cat.code] = cat_obj

    return JsonResponse(payload)
    # 분류별 트리 구조와 flat 조회용 딕셔너리를 하나의 JSON으로 반환.


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
# 이벤트 이력 페이지 한 번에 표시할 행 수.


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
    # GET 파라미터에서 레벨·유형·키워드·날짜 범위·읽음 여부 필터를 읽어옴.

    if q_level:
        qs = qs.filter(alarm_level=q_level)
        # 특정 알람 레벨(위험/경고 등)로 필터링.
    if q_type:
        qs = qs.filter(alarm_type=q_type)
        # 특정 알람 유형(가스/온도 등)으로 필터링.
    if q_keyword:
        qs = qs.filter(
            Q(message__icontains=q_keyword)
            | Q(worker_name__icontains=q_keyword)
            | Q(worker_id__icontains=q_keyword)
            | Q(device_id__icontains=q_keyword)
        )
        # 메시지, 작업자명, 작업자ID, 장비ID 중 어디에든 키워드가 포함되면 매칭.
    if q_unread == "1":
        qs = qs.filter(is_read=False)
        # 읽지 않은 이벤트만 필터링.
    if q_from:
        try:
            dt = datetime.strptime(q_from, "%Y-%m-%d")
            qs = qs.filter(created_at__gte=timezone.make_aware(dt))
            # 시작일 00:00:00 이후 이벤트만 포함. timezone.make_aware로 타임존 적용.
        except ValueError:
            pass
    if q_to:
        try:
            dt = datetime.strptime(q_to, "%Y-%m-%d") + timedelta(days=1)
            qs = qs.filter(created_at__lt=timezone.make_aware(dt))
            # 종료일 다음 날 00:00:00 미만 — 종료일 당일 23:59:59까지 포함.
        except ValueError:
            pass

    qs = qs.order_by("-created_at")
    # 최신 이벤트를 먼저 표시.
    total = qs.count()

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * EVENT_PAGE_SIZE
    rows = list(qs[start : start + EVENT_PAGE_SIZE])
    last_page = max(1, (total + EVENT_PAGE_SIZE - 1) // EVENT_PAGE_SIZE)
    # 전체 건수를 페이지 크기로 나누어 올림하여 마지막 페이지 번호 계산.

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
            # 현재 페이지 기준 앞뒤 4페이지를 페이지네이션 버튼 범위로 제공.
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
    # 이벤트 목록·페이지네이션·필터 선택지를 템플릿에 넘겨 렌더링.


@super_admin_required(menu_code="notifications")
def event_history_csv(request):
    """현재 검색 조건의 이벤트 이력을 CSV 다운로드. 페이지네이션 무시."""
    # event_history 뷰와 동일한 필터 조건으로 쿼리하되, 페이지네이션 없이 전체를 CSV로 다운로드.
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
    # 파일명에 현재 시각을 포함해 중복 다운로드 시 덮어쓰기 방지.
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    # Content-Disposition: attachment 헤더로 브라우저가 파일 저장 다이얼로그를 띄우게 함.
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
        # iterator()로 500건씩 청크 로드 — 대량 데이터를 메모리에 한꺼번에 올리지 않음.
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
    # 알람 이벤트 1건의 전체 필드를 JSON으로 반환. 목록에서 행 클릭 시 모달 팝업에 데이터 로드.
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
                # 작업자 발생 위치 좌표 — 지도 마커 표시에 활용.
                "device_id": a.device_id,
                "sensor_type": a.sensor_type,
                "message": a.message,
                "is_read": a.is_read,
                "geofence_name": a.geofence.name if a.geofence else None,
                # 알람이 발생한 지오펜스 구역 이름. 연결된 구역이 없으면 None.
            }
        }
    )
    # 이벤트 상세 데이터를 모달 팝업용으로 반환.


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def event_bulk_read_api(request):
    """선택 이벤트 일괄 읽음 처리."""
    # 체크박스로 선택한 이벤트들을 한 번에 "읽음" 상태로 변경하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Alarm.objects.filter(id__in=ids, is_read=False).update(is_read=True)
    # 이미 읽은 이벤트는 건너뛰고 아직 읽지 않은 것만 업데이트하여 불필요한 DB 변경 방지.
    return JsonResponse({"ok": True, "updated": n})
    # 실제로 읽음 처리된 건수를 반환.


# ═══════════════════════════════════════════════════════════
# 알림 정책 관리
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="notifications")
def notification_policy_list(request):
    # 알림 정책 목록 페이지. 등록·수정 모달에 필요한 선택지 데이터를 함께 전달.
    rows = list(
        NotificationPolicy.objects.select_related("risk_category", "alarm_level").all()
    )
    # 위험 분류·알람 단계를 JOIN으로 함께 로드하여 N+1 방지.
    return render(
        request,
        "backoffice/notifications/policy_list.html",
        {
            "rows": rows,
            "risk_categories": RiskCategory.objects.filter(is_active=True),
            # 활성 위험 분류만 드롭다운 선택지로 제공.
            "alarm_levels": AlarmLevel.objects.filter(is_active=True).order_by(
                "priority"
            ),
            # 활성 알람 단계를 우선순위 순으로 드롭다운에 제공.
            "organizations": Organization.objects.filter(
                parent__isnull=False, is_unassigned_bucket=False
            ),
            # 루트·가상 버킷을 제외한 실제 부서만 수신 대상 선택지로 제공.
            "channel_choices": NOTIFICATION_CHANNEL_CHOICES,
            "active_menu": "notification_policies",
        },
    )
    # 정책 목록과 모달용 선택지 데이터를 템플릿에 넘겨 렌더링.


def _policy_to_dict(p: NotificationPolicy) -> dict:
    # NotificationPolicy 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
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
        # 발송 채널 목록 (예: "push,sms") — 콤마 구분 문자열.
        "channels_list": p.channels_list,
        # channels_csv를 리스트로 파싱한 프로퍼티.
        "recipients_csv": p.recipients_csv,
        # 수신 대상 (조직 코드 또는 사용자 ID 목록) — 콤마 구분 문자열.
        "recipients_list": p.recipients_list,
        "message_template": p.message_template,
        # 발송 메시지 템플릿 — {worker_name}, {alarm_level} 등의 플레이스홀더 포함 가능.
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else "-",
    }


@super_admin_required_api(menu_code="notifications", action="read")
@require_GET
def policy_detail_api(request, pk):
    # 알림 정책 1건의 상세 정보를 JSON으로 반환. 수정 모달 데이터 로드에 사용.
    p = get_object_or_404(
        NotificationPolicy.objects.select_related("risk_category", "alarm_level"),
        pk=pk,
    )
    # 위험 분류·알람 단계를 JOIN으로 함께 로드하여 N+1 방지.
    return JsonResponse({"policy": _policy_to_dict(p)})
    # 알림 정책 데이터를 dict로 변환하여 반환.


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_create_api(request):
    # 새 알림 정책을 생성하는 API.
    form = NotificationPolicyForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "policy": _policy_to_dict(p)})
    # 생성된 알림 정책 정보를 응답으로 반환.


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_update_api(request, pk):
    # 기존 알림 정책을 수정하는 API.
    p = get_object_or_404(NotificationPolicy, pk=pk)
    form = NotificationPolicyForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "policy": _policy_to_dict(p)})
    # 수정된 알림 정책 정보를 응답으로 반환.


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_bulk_delete_api(request):
    # 선택된 알림 정책 여러 건을 일괄 삭제하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = NotificationPolicy.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
    # 삭제된 건수를 응답으로 반환.


@super_admin_required_api(menu_code="notifications", action="write")
@require_POST
def policy_bulk_toggle_api(request):
    # 선택된 알림 정책들의 활성/비활성 상태를 일괄 변경하는 API.
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    # 목표 활성 상태를 bool로 변환.
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = NotificationPolicy.objects.filter(id__in=ids).update(is_active=target)
    # 선택된 정책들의 is_active 필드를 한 번의 쿼리로 일괄 업데이트.
    return JsonResponse({"ok": True, "updated": n})
    # 업데이트된 건수를 응답으로 반환.


# ═══════════════════════════════════════════════════════════
# 알림 발송 이력
# ═══════════════════════════════════════════════════════════

NOTIF_LOG_PAGE_SIZE = 30
# 알림 발송 이력 페이지 한 번에 표시할 행 수.


@super_admin_required(menu_code="notifications")
def notification_log_list(request):
    # 알림 발송 이력 조회 페이지. 발송 상태·채널·키워드·날짜 범위 필터 지원.
    qs = NotificationLog.objects.select_related("policy", "recipient", "alarm").all()
    # 정책·수신자·알람을 JOIN으로 함께 로드하여 N+1 방지.

    q_status = request.GET.get("status", "").strip()
    q_channel = request.GET.get("channel", "").strip()
    q_keyword = request.GET.get("keyword", "").strip()
    q_from = request.GET.get("from", "").strip()
    q_to = request.GET.get("to", "").strip()

    if q_status:
        qs = qs.filter(send_status=q_status)
        # 발송 상태(sent/failed/pending)로 필터링.
    if q_channel:
        qs = qs.filter(channel=q_channel)
        # 발송 채널(push/sms 등)로 필터링.
    if q_keyword:
        qs = qs.filter(
            Q(recipient_name_snapshot__icontains=q_keyword)
            | Q(error_message__icontains=q_keyword)
            | Q(policy__name__icontains=q_keyword)
        )
        # 수신자명, 오류 메시지, 정책명 중 어디에든 키워드가 포함되면 매칭.
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
    # 최신 발송 이력을 먼저 표시.
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
    # 최근 24시간 동안의 발송 이력만 별도 집계하여 대시보드 통계 카드에 표시.
    stats = {
        "total": total,
        "sent_24h": stats_24h.filter(send_status="sent").count(),
        # 24시간 내 성공 발송 건수.
        "failed_24h": stats_24h.filter(send_status="failed").count(),
        # 24시간 내 실패 건수 — 운영자가 주목해야 할 수치.
        "pending_24h": stats_24h.filter(send_status="pending").count(),
        # 24시간 내 대기 중인 건수.
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
    # 발송 이력 목록·통계·페이지네이션을 템플릿에 넘겨 렌더링.


# ═══════════════════════════════════════════════════════════
# 메뉴 관리
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="menus")
def menu_management(request):
    """역할 ↔ 메뉴 매트릭스. super_admin 은 항상 전체.
    admin 만 토글 가능.
    """
    # 메뉴별 admin 역할의 열람·쓰기 권한 현황을 매트릭스 형태로 표시하는 페이지.
    perms = MenuPermission.objects.filter(role="admin")
    # admin 역할의 MenuPermission 레코드를 가져옴. super_admin은 코드레벨에서 항상 전체 허용.
    perm_map = {p.menu_code: p for p in perms}
    # 빠른 조회를 위해 menu_code → 권한 객체 dict로 변환.
    rows = []
    for code, label in MENU_CODE_CHOICES:
        p = perm_map.get(code)
        # DB에 레코드가 없으면 기본값 False로 처리(미설정 = 비허용).
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
    # 메뉴별 권한 현황 목록을 템플릿에 넘겨 매트릭스 화면을 렌더링.


@super_admin_required_api(menu_code="menus", action="write")
@require_POST
def menu_perm_update_api(request):
    """단일 권한 토글. body: {role, menu_code, is_visible, is_writable}"""
    # 특정 역할의 특정 메뉴 권한(열람·쓰기)을 토글하는 API. 매트릭스 체크박스 클릭 시 호출.
    data = _parse_json(request)
    form = MenuPermissionUpdateForm(data)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    role = form.cleaned_data["role"]
    menu_code = form.cleaned_data["menu_code"]

    p, _ = MenuPermission.objects.get_or_create(role=role, menu_code=menu_code)
    # 해당 역할·메뉴 조합의 권한 레코드가 없으면 새로 생성, 있으면 기존 것 사용.
    # 명시적 토글 - is_writable 은 is_visible 일 때만 의미가 있어 강제
    is_visible = bool(data.get("is_visible"))
    is_writable = bool(data.get("is_writable")) and is_visible
    # 열람 권한이 없으면 쓰기 권한도 자동으로 False — 메뉴가 안 보이는데 쓰기만 허용하는 모순 방지.
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
    # 변경된 권한 내용을 응답으로 반환하여 프런트가 즉시 UI를 갱신할 수 있게 함.


# ═══════════════════════════════════════════════════════════
# 설비/장비 관리 — 피그마 '설비/장비 관리'
# ═══════════════════════════════════════════════════════════
from devices.models import Device, SENSOR_TYPE_CHOICES as DEVICE_SENSOR_TYPE_CHOICES
from geofence.models import GeoFence, ZONE_TYPE_CHOICES, RISK_LEVEL_CHOICES
from dashboard.models import MapImage

from .models import DataRetentionPolicy, Notice, NOTICE_CATEGORY_CHOICES
from .forms import DeviceForm, GeoFenceForm, DataRetentionForm, NoticeForm


DEVICE_PAGE_SIZE = 20
# 장비 목록 페이지 한 번에 표시할 행 수.


@super_admin_required(menu_code="devices")
def device_list(request):
    # 설비/장비 목록 페이지. 키워드·센서 유형·상태·활성 여부로 필터링 지원.
    qs = Device.objects.select_related("geofence").all()
    # 지오펜스를 JOIN으로 함께 로드하여 N+1 방지.

    q_keyword = request.GET.get("keyword", "").strip()
    q_type = request.GET.get("type", "").strip()
    q_status = request.GET.get("status", "").strip()
    q_active = request.GET.get("active", "").strip()

    if q_keyword:
        qs = qs.filter(
            Q(device_id__icontains=q_keyword) | Q(device_name__icontains=q_keyword)
        )
        # 장비 ID 또는 장비명에 키워드가 포함되면 매칭.
    if q_type:
        qs = qs.filter(sensor_type=q_type)
        # 특정 센서 유형으로 필터링.
    if q_status:
        qs = qs.filter(status=q_status)
        # 연결 상태(online/offline 등)로 필터링.
    if q_active == "1":
        qs = qs.filter(is_active=True)
        # 활성 장비만 표시.
    elif q_active == "0":
        qs = qs.filter(is_active=False)
        # 비활성 장비만 표시.

    qs = qs.order_by("device_id")
    # 장비 ID 알파벳순으로 정렬.
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
            # 센서 유형 필터 드롭다운에 사용할 choices.
            "geofences": GeoFence.objects.all().order_by("name"),
            # 장비 등록/수정 모달에서 지오펜스 선택지로 제공.
            "q": {
                "keyword": q_keyword,
                "type": q_type,
                "status": q_status,
                "active": q_active,
            },
            "active_menu": "devices",
        },
    )
    # 장비 목록·페이지네이션·필터 선택지를 템플릿에 넘겨 렌더링.


def _device_to_dict(d: Device) -> dict:
    # Device 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": d.id,
        "device_id": d.device_id,
        # 장비 고유 식별자 — 하드웨어 또는 외부 시스템이 사용하는 ID.
        "device_name": d.device_name,
        "sensor_type": d.sensor_type,
        "sensor_type_display": d.get_sensor_type_display(),
        "x": d.x,
        "y": d.y,
        # 장비의 지도상 좌표. 지오펜스 자동 매핑과 마커 표시에 사용.
        "status": d.status,
        "status_display": d.get_status_display(),
        "last_value": d.last_value,
        # 마지막으로 수신된 센서 측정값.
        "last_value_unit": d.last_value_unit,
        "is_active": d.is_active,
        "geofence_id": d.geofence_id,
        "geofence_name": d.geofence.name if d.geofence else None,
        # 장비가 속한 지오펜스 구역 이름. 없으면 None.
    }


@super_admin_required_api(menu_code="devices", action="read")
@require_GET
def device_detail_api(request, pk):
    # 특정 장비 1건의 상세 정보를 JSON으로 반환. 수정 모달 데이터 로드에 사용.
    d = get_object_or_404(Device.objects.select_related("geofence"), pk=pk)
    # 지오펜스를 JOIN으로 함께 로드하여 N+1 방지.
    return JsonResponse({"device": _device_to_dict(d)})
    # 장비 데이터를 dict로 변환하여 반환.


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_create_api(request):
    # 새 장비를 등록하는 API.
    form = DeviceForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    d = form.save(by=request.user)
    return JsonResponse({"ok": True, "device": _device_to_dict(d)})
    # 등록된 장비 정보를 응답으로 반환.


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_update_api(request, pk):
    # 기존 장비 정보를 수정하는 API.
    d = get_object_or_404(Device, pk=pk)
    form = DeviceForm(_parse_json(request), instance=d)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    d = form.save(by=request.user)
    return JsonResponse({"ok": True, "device": _device_to_dict(d)})
    # 수정된 장비 정보를 응답으로 반환.


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_bulk_delete_api(request):
    # 선택된 장비 여러 건을 일괄 삭제하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Device.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
    # 삭제된 건수를 응답으로 반환.


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_bulk_toggle_api(request):
    # 선택된 장비들의 활성/비활성 상태를 일괄 변경하는 API.
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_active"))
    # 목표 활성 상태를 bool로 변환.
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Device.objects.filter(id__in=ids).update(is_active=target)
    # 선택된 장비들의 is_active 필드를 한 번의 쿼리로 일괄 업데이트.
    return JsonResponse({"ok": True, "updated": n})
    # 업데이트된 건수를 응답으로 반환.


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_auto_map_geofence_api(request):
    """현재 좌표 기준으로 모든 장비의 geofence 를 자동 매핑.
    기존 매핑이 있어도 강제 재계산.
    """
    # 모든 장비의 (x, y) 좌표를 기준으로 어느 지오펜스 구역에 속하는지 자동으로 재계산.
    from .geo_utils import find_containing_geofence

    active_fences = list(GeoFence.objects.filter(is_active=True))
    # 활성 지오펜스 목록을 메모리에 캐시하여 장비마다 DB 조회하지 않음.
    updated = 0
    cleared = 0
    for d in Device.objects.all():
        matched = find_containing_geofence(d.x, d.y, active_fences)
        # 장비 좌표가 포함되는 지오펜스를 탐색.
        if matched and d.geofence_id != matched.id:
            d.geofence = matched
            d.save(update_fields=["geofence"])
            updated += 1
            # 지오펜스가 변경된 경우만 저장 — 동일하면 불필요한 DB 쓰기 방지.
        elif not matched and d.geofence_id is not None:
            d.geofence = None
            d.save(update_fields=["geofence"])
            cleared += 1
            # 어떤 구역에도 속하지 않는 장비는 geofence를 None으로 초기화.
    return JsonResponse({"ok": True, "mapped": updated, "cleared": cleared})
    # 새로 매핑된 수(mapped)와 매핑 해제된 수(cleared)를 반환.


@super_admin_required_api(menu_code="devices", action="write")
@require_POST
def device_csv_upload_api(request):
    """CSV 일괄 등록.

    [v6] mode=create (default) | upsert + DeviceHistory 자동 기록.
    형식: device_id,device_name,sensor_type,x,y,is_active,last_value_unit
    """
    # CSV 파일로 장비를 일괄 등록(create) 또는 등록+수정(upsert)하는 API.
    if "file" not in request.FILES:
        return JsonResponse(
            {"ok": False, "error": "파일이 첨부되지 않았습니다."}, status=400
        )
    f = request.FILES["file"]
    if f.size > 5 * 1024 * 1024:
        return JsonResponse(
            {"ok": False, "error": "파일 크기는 5MB 이하여야 합니다."}, status=400
        )
        # 5MB 초과 파일은 서버 메모리 부담 방지를 위해 거부.

    mode = (request.POST.get("mode") or "create").strip().lower()
    # create: 신규만 등록, upsert: 기존 있으면 수정, 없으면 신규 등록.
    if mode not in ("create", "upsert"):
        return JsonResponse(
            {"ok": False, "error": "mode 는 'create' 또는 'upsert' 여야 합니다."},
            status=400,
        )

    try:
        text = f.read().decode("utf-8-sig")
        # utf-8-sig: BOM 포함 UTF-8도 정상 디코딩 (Excel 저장 파일 대응).
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
    # 유효한 sensor_type 코드 집합으로 미리 생성하여 행별 검증에 사용.
    created, updated, skipped, errors = 0, 0, 0, []
    existing_by_id = {d.device_id: d for d in Device.objects.all()}
    # 전체 장비를 device_id 키로 캐시하여 행마다 DB 조회하지 않음.

    from .geo_utils import find_containing_geofence
    from .audit import write_device_history

    active_fences = list(GeoFence.objects.filter(is_active=True))
    # 활성 지오펜스를 메모리에 캐시하여 행마다 DB 조회 방지.

    for line_no, row in enumerate(reader, start=2):
        # 행 번호를 2부터 시작(헤더=1)하여 에러 메시지에 포함.
        device_id = (row.get("device_id") or "").strip()
        device_name = (row.get("device_name") or "").strip()
        sensor_type = (row.get("sensor_type") or "").strip()
        try:
            x = float(row.get("x", 0))
            y = float(row.get("y", 0))
        except ValueError:
            errors.append({"line": line_no, "error": "좌표가 숫자가 아닙니다."})
            continue
            # 좌표 파싱 실패 시 해당 행만 에러 기록하고 다음 행으로 계속 진행.
        is_active_raw = (row.get("is_active") or "").strip().lower()
        is_active = is_active_raw in ("1", "true", "on", "yes", "y", "활성")
        # 다양한 표현(1/true/on/yes/y/활성)을 True로 파싱.
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
            # 유효하지 않은 sensor_type은 에러로 기록.

        existing = existing_by_id.get(device_id)
        matched = find_containing_geofence(x, y, active_fences)
        # 이 장비 좌표에 해당하는 지오펜스를 탐색.

        if existing:
            if mode == "create":
                skipped += 1
                continue
                # create 모드에서 이미 존재하는 장비는 건너뜀.
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
                # 변경 내역을 DeviceHistory에 기록하여 감사 추적 가능.
                updated += 1
            else:
                skipped += 1
                # 실제 변경 내용이 없으면 저장 없이 건너뜀.
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
            # 새로 생성한 장비를 캐시에 추가하여 같은 파일 내 중복 ID 처리.
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
            # 에러는 최대 50건만 반환 — 응답 크기 제한.
        }
    )
    # 처리 결과(신규/수정/건너뜀/오류 건수)를 응답으로 반환.


# ═══════════════════════════════════════════════════════════
# 지도 편집 관리 — 피그마 '지도 편집 관리'
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="maps")
def map_edit(request):
    """지도 + 지오펜스 + 장비 통합 편집 화면.
    피그마: 좌측 캔버스 (지도 + 지오펜스 폴리곤 + 장비 마커),
    우측 패널 (지오펜스 목록·등록·수정).
    """
    # 지도 이미지·지오펜스·장비를 한 화면에서 편집하는 통합 관리 페이지.
    active_map = (
        MapImage.objects.filter(is_active=True).first() or MapImage.objects.first()
    )
    # 활성 지도 이미지를 우선 사용. 없으면 가장 최근 업로드된 지도를 fallback.
    geofences = list(GeoFence.objects.all().order_by("-created_at"))
    # 전체 지오펜스를 최신 등록순으로 가져와 우측 패널 목록에 표시.
    devices_with_geo = list(
        Device.objects.filter(is_active=True).select_related("geofence")
    )
    # 활성 장비만 지도 마커로 표시. 지오펜스를 JOIN으로 함께 로드.
    return render(
        request,
        "backoffice/maps/edit.html",
        {
            "active_map": active_map,
            "geofences": geofences,
            "devices": devices_with_geo,
            "maps": MapImage.objects.all().order_by("-uploaded_at"),
            # 지도 선택 드롭다운에 업로드된 모든 지도 이미지를 최신순으로 제공.
            "zone_types": ZONE_TYPE_CHOICES,
            # 지오펜스 등록 모달의 구역 유형 선택지.
            "risk_levels": RISK_LEVEL_CHOICES,
            # 지오펜스 등록 모달의 위험 등급 선택지.
            "active_menu": "maps",
        },
    )
    # 지도·지오펜스·장비·선택지 데이터를 템플릿에 넘겨 편집 화면을 렌더링.


def _gf_to_dict(g: GeoFence) -> dict:
    # GeoFence 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": g.id,
        "name": g.name,
        "zone_type": g.zone_type,
        "zone_type_display": g.get_zone_type_display(),
        "risk_level": g.risk_level,
        # 위험 등급 코드 (예: "high", "medium", "low").
        "risk_level_display": g.get_risk_level_display(),
        "description": g.description,
        "polygon": g.polygon,
        # 지오펜스 경계를 나타내는 폴리곤 좌표 목록 (JSON 배열).
        "is_active": g.is_active,
        "device_count": g.devices.count(),
        # 이 구역에 속한 장비 수.
        "created_at": g.created_at.strftime("%Y-%m-%d %H:%M") if g.created_at else "-",
    }


@super_admin_required_api(menu_code="maps", action="read")
@require_GET
def geofence_detail_api(request, pk):
    # 특정 지오펜스 1건의 상세 정보를 JSON으로 반환. 수정 패널 데이터 로드에 사용.
    g = get_object_or_404(GeoFence, pk=pk)
    return JsonResponse({"geofence": _gf_to_dict(g)})
    # 지오펜스 데이터를 dict로 변환하여 반환.


@super_admin_required_api(menu_code="maps", action="write")
@require_POST
def geofence_create_api(request):
    # 새 지오펜스 구역을 생성하는 API. 폴리곤 좌표와 구역 속성을 함께 저장.
    form = GeoFenceForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save()
    return JsonResponse({"ok": True, "geofence": _gf_to_dict(g)})
    # 생성된 지오펜스 정보를 응답으로 반환.


@super_admin_required_api(menu_code="maps", action="write")
@require_POST
def geofence_update_api(request, pk):
    # 기존 지오펜스를 수정하는 API. 폴리곤 좌표나 구역 속성 변경에 사용.
    g = get_object_or_404(GeoFence, pk=pk)
    form = GeoFenceForm(_parse_json(request), instance=g)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    g = form.save()
    return JsonResponse({"ok": True, "geofence": _gf_to_dict(g)})
    # 수정된 지오펜스 정보를 응답으로 반환.


@super_admin_required_api(menu_code="maps", action="write")
@require_POST
def geofence_delete_api(request, pk):
    # 지오펜스 구역을 삭제하는 API.
    g = get_object_or_404(GeoFence, pk=pk)
    # 소속 device 의 geofence FK 는 SET_NULL 로 자동 풀림
    # 이 구역에 속해있던 장비들은 DB 레벨에서 SET_NULL로 자동 처리 — 별도 코드 불필요.
    g.delete()
    return JsonResponse({"ok": True})
    # 삭제 완료 응답.


# ═══════════════════════════════════════════════════════════
# 운영 데이터 관리 (보관 정책)
# ═══════════════════════════════════════════════════════════


@super_admin_required(menu_code="operations")
def retention_list(request):
    # 데이터 보관 정책 목록 페이지. 각 데이터 유형별 현재 누적 건수도 함께 표시.
    rows = list(DataRetentionPolicy.objects.all().order_by("target"))
    # 보관 정책을 대상 모델(target) 알파벳순으로 정렬.

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
        # 현재 각 테이블의 전체 레코드 수를 표시하여 정책 실행 전 영향 범위를 파악할 수 있게 함.
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
    # 보관 정책 목록과 현재 누적 건수를 템플릿에 넘겨 렌더링.


def _retention_to_dict(p: DataRetentionPolicy) -> dict:
    # DataRetentionPolicy 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": p.id,
        "target": p.target,
        # 보관 정책이 적용되는 데이터 테이블 코드 (예: "sensor_data").
        "target_display": p.get_target_display(),
        "retention_days": p.retention_days,
        # 이 일수보다 오래된 레코드를 삭제 대상으로 설정.
        "is_active": p.is_active,
        "last_run_at": (
            p.last_run_at.strftime("%Y-%m-%d %H:%M") if p.last_run_at else None
        ),
        # 마지막으로 정책이 실행된 시각.
        "last_run_deleted": p.last_run_deleted,
        # 마지막 실행에서 삭제된 레코드 수.
        "description": p.description,
        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else "-",
    }


@super_admin_required_api(menu_code="operations", action="read")
@require_GET
def retention_detail_api(request, pk):
    # 특정 보관 정책 1건의 상세 정보를 JSON으로 반환. 수정 모달 데이터 로드에 사용.
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    return JsonResponse({"retention": _retention_to_dict(p)})
    # 보관 정책 데이터를 dict로 변환하여 반환.


@super_admin_required_api(menu_code="operations", action="write")
@require_POST
def retention_update_api(request, pk):
    # 보관 정책의 보관 기간(retention_days)이나 활성 여부 등을 수정하는 API.
    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    form = DataRetentionForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    p = form.save(by=request.user)
    return JsonResponse({"ok": True, "retention": _retention_to_dict(p)})
    # 수정된 보관 정책 정보를 응답으로 반환.


@super_admin_required_api(menu_code="operations", action="write")
@require_POST
def retention_run_now_api(request, pk):
    """단건 정책 즉시 실행 — 백그라운드 큐 없이 동기로 처리.
    레코드 수가 많으면 timeout 가능성 있어 v6 에서 큐로 분리 권장.
    """
    # 보관 정책을 즉시 동기 실행하는 API. 보관 기간을 초과한 데이터를 바로 삭제.
    from datetime import timedelta as _td
    from .management.commands.cleanup_data import _resolve_qs

    p = get_object_or_404(DataRetentionPolicy, pk=pk)
    if not p.is_active:
        return JsonResponse(
            {"ok": False, "error": "비활성 정책은 실행할 수 없습니다."}, status=400
        )
        # 비활성 정책은 실행 불가 — 실수로 트리거되는 것을 방지.

    cutoff = timezone.now() - _td(days=p.retention_days)
    # 현재 시각에서 retention_days일을 뺀 기준 시각을 계산.
    qs = _resolve_qs(p.target, cutoff)
    # 대상 모델과 기준 시각으로 삭제할 QuerySet을 가져옴.
    if qs is None:
        return JsonResponse(
            {"ok": False, "error": "대상 모델 매핑이 없습니다."}, status=400
        )
        # target 코드에 해당하는 모델 매핑이 없으면 에러.

    deleted, _ = qs.delete()
    # 기준 시각 이전의 레코드를 일괄 삭제.
    p.last_run_at = timezone.now()
    p.last_run_deleted = deleted
    p.save(update_fields=["last_run_at", "last_run_deleted"])
    # 실행 시각과 삭제 건수를 정책 레코드에 기록.
    return JsonResponse(
        {"ok": True, "deleted": deleted, "retention": _retention_to_dict(p)}
    )
    # 삭제 건수와 갱신된 정책 정보를 응답으로 반환.


# ═══════════════════════════════════════════════════════════
# 공지사항 관리
# ═══════════════════════════════════════════════════════════

NOTICE_PAGE_SIZE = 20
# 공지사항 목록 페이지 한 번에 표시할 행 수.


@super_admin_required(menu_code="notices")
def notice_list(request):
    # 공지사항 목록 페이지. 키워드·카테고리·게시 여부로 필터링 지원.
    qs = Notice.objects.all()

    q_keyword = request.GET.get("keyword", "").strip()
    q_category = request.GET.get("category", "").strip()
    q_published = request.GET.get("published", "").strip()

    if q_keyword:
        qs = qs.filter(Q(title__icontains=q_keyword) | Q(content__icontains=q_keyword))
        # 제목 또는 내용에 키워드가 포함되면 매칭.
    if q_category:
        qs = qs.filter(category=q_category)
        # 특정 카테고리의 공지만 필터링.
    if q_published == "1":
        qs = qs.filter(is_published=True)
        # 게시된 공지만 표시.
    elif q_published == "0":
        qs = qs.filter(is_published=False)
        # 미게시 공지만 표시.

    qs = qs.order_by("-is_pinned", "-created_at")
    # 고정된 공지를 먼저 표시하고, 같은 조건에서는 최신 등록순으로 정렬.
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
            # 카테고리 필터 드롭다운에 사용할 choices.
            "q": {
                "keyword": q_keyword,
                "category": q_category,
                "published": q_published,
            },
            "active_menu": "notices",
        },
    )
    # 공지 목록·페이지네이션·필터 선택지를 템플릿에 넘겨 렌더링.


def _notice_to_dict(n: Notice) -> dict:
    # Notice 모델을 JSON 직렬화 가능한 dict로 변환하는 헬퍼.
    return {
        "id": n.id,
        "title": n.title,
        "category": n.category,
        "category_display": n.get_category_display(),
        "content": n.content,
        "is_pinned": n.is_pinned,
        # True이면 목록 최상단에 고정 표시.
        "is_published": n.is_published,
        "published_from": (
            n.published_from.strftime("%Y-%m-%dT%H:%M") if n.published_from else None
        ),
        # 게시 시작 일시. None이면 즉시 게시.
        "published_to": (
            n.published_to.strftime("%Y-%m-%dT%H:%M") if n.published_to else None
        ),
        # 게시 종료 일시. None이면 무기한 게시.
        "view_count": n.view_count,
        # 조회수.
        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "-",
        "created_by_name": n.created_by.first_name if n.created_by else "-",
    }


@super_admin_required_api(menu_code="notices", action="read")
@require_GET
def notice_detail_api(request, pk):
    # 특정 공지사항 1건의 상세 정보를 JSON으로 반환. 수정 모달 데이터 로드에 사용.
    n = get_object_or_404(Notice, pk=pk)
    return JsonResponse({"notice": _notice_to_dict(n)})
    # 공지사항 데이터를 dict로 변환하여 반환.


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_create_api(request):
    # 새 공지사항을 생성하는 API. send_notify 옵션으로 생성 즉시 알림 발송도 가능.
    form = NoticeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    n = form.save(by=request.user)

    # v5 — 게시 + send_notify 옵션 시 즉시 발송
    payload = _parse_json(request)
    if payload.get("send_notify") and n.is_published:
        # send_notify=True이고 공지가 게시 상태일 때만 알림을 발송.
        from .notification_dispatcher import dispatch_for_notice

        try:
            dispatched = dispatch_for_notice(n)
            return JsonResponse(
                {"ok": True, "notice": _notice_to_dict(n), "dispatched": dispatched}
            )
            # 알림 발송 성공 시 발송 건수를 포함하여 반환.
        except Exception as e:
            # 알림 발송 실패는 공지 등록 자체엔 영향 없음
            return JsonResponse(
                {"ok": True, "notice": _notice_to_dict(n), "notify_error": str(e)}
            )
            # 발송 오류는 공지 저장을 롤백하지 않고 오류 메시지만 포함하여 반환.

    return JsonResponse({"ok": True, "notice": _notice_to_dict(n)})
    # 알림 발송 없이 공지 생성만 완료.


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_dispatch_api(request, pk):
    """기존 공지를 수동으로 사용자에게 알림 발송."""
    # 이미 저장된 공지사항을 수동으로 알림 발송하는 API. 미게시 공지는 발송 불가.
    n = get_object_or_404(Notice, pk=pk)
    if not n.is_published:
        return JsonResponse(
            {"ok": False, "error": "미게시 공지는 발송할 수 없습니다."}, status=400
        )
        # 아직 게시되지 않은 공지는 외부에 노출되면 안 되므로 발송 차단.
    from .notification_dispatcher import dispatch_for_notice

    channels = _parse_json(request).get("channels") or ["app", "realtime"]
    # 발송 채널을 요청 body에서 지정 가능. 기본값은 앱 푸시와 실시간 알림.
    dispatched = dispatch_for_notice(n, channels=channels)
    return JsonResponse({"ok": True, "dispatched": dispatched})
    # 실제 발송된 알림 건수를 응답으로 반환.


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_update_api(request, pk):
    # 기존 공지사항을 수정하는 API.
    n = get_object_or_404(Notice, pk=pk)
    form = NoticeForm(_parse_json(request), instance=n)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": _form_errors_payload(form)}, status=400
        )
    n = form.save(by=request.user)
    return JsonResponse({"ok": True, "notice": _notice_to_dict(n)})
    # 수정된 공지사항 정보를 응답으로 반환.


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_bulk_delete_api(request):
    # 선택된 공지사항 여러 건을 일괄 삭제하는 API.
    ids = _parse_json(request).get("ids") or []
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    deleted, _ = Notice.objects.filter(id__in=ids).delete()
    return JsonResponse({"ok": True, "deleted": deleted})
    # 삭제된 건수를 응답으로 반환.


@super_admin_required_api(menu_code="notices", action="write")
@require_POST
def notice_bulk_toggle_api(request):
    # 선택된 공지사항들의 게시/미게시 상태를 일괄 변경하는 API.
    data = _parse_json(request)
    ids = data.get("ids") or []
    target = bool(data.get("is_published"))
    # 목표 게시 상태를 bool로 변환.
    if not ids:
        return JsonResponse({"ok": False, "error": "대상 없음"}, status=400)
    n = Notice.objects.filter(id__in=ids).update(is_published=target)
    # 선택된 공지들의 is_published 필드를 한 번의 쿼리로 일괄 업데이트.
    return JsonResponse({"ok": True, "updated": n})
    # 업데이트된 건수를 응답으로 반환.


# ═══════════════════════════════════════════════════════════
# v6 — Audit Log 조회 페이지 + Device History API
# ═══════════════════════════════════════════════════════════

AUDIT_PAGE_SIZE = 30
# 감사 로그 페이지 한 번에 표시할 행 수.


@super_admin_required(menu_code="operations")
def audit_log_list(request):
    # 관리자 행동 감사 로그 조회 페이지. 액션·대상 모델·키워드·날짜 범위 필터 지원.
    from .models import AuditLog, AUDIT_ACTION_CHOICES

    qs = AuditLog.objects.select_related("actor").all()
    # 행동 주체(actor 사용자)를 JOIN으로 함께 로드하여 N+1 방지.

    q_action = request.GET.get("action", "").strip()
    q_target = request.GET.get("target_model", "").strip()
    q_keyword = request.GET.get("keyword", "").strip()
    q_from = request.GET.get("from", "").strip()
    q_to = request.GET.get("to", "").strip()

    if q_action:
        qs = qs.filter(action=q_action)
        # 특정 액션(create/update/delete 등)으로 필터링.
    if q_target:
        qs = qs.filter(target_model=q_target)
        # 특정 대상 모델(User/Device 등)로 필터링.
    if q_keyword:
        qs = qs.filter(
            Q(actor_username_snapshot__icontains=q_keyword)
            | Q(target_repr__icontains=q_keyword)
            | Q(extra_message__icontains=q_keyword)
            | Q(request_path__icontains=q_keyword)
        )
        # 행동 주체 ID, 대상 표현, 메시지, 요청 경로 중 어디에든 키워드가 포함되면 매칭.
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
    # 최신 로그를 먼저 표시.
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
    # 실제 로그에 등장하는 모델명을 동적으로 수집하여 필터 드롭다운에 제공.

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
            # 액션 필터 드롭다운에 사용할 choices.
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
    # 감사 로그 목록·페이지네이션·필터 선택지를 템플릿에 넘겨 렌더링.


@super_admin_required_api(menu_code="devices", action="read")
@require_GET
def device_history_api(request, pk):
    """단일 장비의 변경 이력. 모달 표시용."""
    # 특정 장비의 변경 이력 최대 50건을 JSON으로 반환. 장비 목록에서 이력 모달 열기 시 사용.
    from .models import DeviceHistory

    d = get_object_or_404(Device, pk=pk)
    history = DeviceHistory.objects.filter(device_id_snapshot=d.device_id).order_by(
        "-created_at"
    )[:50]
    # device_id_snapshot으로 조회 — 장비가 삭제·재생성된 경우에도 이력 추적 가능.
    # 최근 50건만 가져와 모달 표시에 충분한 양으로 제한.
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
                    # 행동 주체 ID 스냅샷 — 사용자가 삭제되어도 이력 보존.
                    "changes": h.changes,
                    # 변경 전·후 값을 담은 dict (예: {"device_name": ["old", "new"]}).
                    "message": h.extra_message,
                    "created_at": h.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for h in history
            ],
        }
    )
    # 장비 기본 정보와 변경 이력 목록을 묶어 반환.
