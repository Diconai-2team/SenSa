"""
backoffice/views/masters.py — 코어 마스터 (참조 데이터) 관리.

4개 도메인을 한 모듈로 묶음:
  - 공통 코드 (CodeGroup + Code) — 피그마 '공통 코드 관리'
  - 위험 유형 (RiskCategory + RiskType) — 피그마 '위험 유형 관리'
  - 위험 기준 (AlarmLevel) — 피그마 '위험 기준 관리'
  - 임계치 (ThresholdCategory + Threshold) — 피그마 '임계치 기준 관리'

이들 4개는 모두 menu_code='references' 권한을 공유하고, 같은 마스터 데이터
관리 패턴 (그룹/카테고리 + 항목, 시스템 보호) 을 따름. 그래서 한 파일에 묶음.

추가:
  - thresholds_for_fastapi: FastAPI 가 GAS_THRESHOLDS 대체용으로 폴링하는 내부 API.
    임계치 도메인과 직결되므로 같이 둠.

라우팅:
  공통 코드:
    GET  /backoffice/codes/                          → code_manage
    GET  /backoffice/api/code-groups/<pk>/           → code_group_detail_api
    POST /backoffice/api/code-groups/create/         → code_group_create_api
    POST /backoffice/api/code-groups/<pk>/update/    → code_group_update_api
    POST /backoffice/api/code-groups/<pk>/delete/    → code_group_delete_api
    POST /backoffice/api/codes/create/               → code_create_api
    POST /backoffice/api/codes/<pk>/update/          → code_update_api
    POST /backoffice/api/codes/bulk-delete/          → code_bulk_delete_api
    POST /backoffice/api/codes/bulk-toggle/          → code_bulk_toggle_api

  위험 유형:
    GET  /backoffice/risks/                          → risk_manage
    GET  /backoffice/api/risk-categories/<pk>/       → risk_cat_detail_api
    POST /backoffice/api/risk-categories/create/     → risk_cat_create_api
    POST /backoffice/api/risk-categories/<pk>/update/ → risk_cat_update_api
    POST /backoffice/api/risk-categories/<pk>/delete/ → risk_cat_delete_api
    POST /backoffice/api/risk-types/create/          → risk_type_create_api
    POST /backoffice/api/risk-types/<pk>/update/     → risk_type_update_api
    POST /backoffice/api/risk-types/bulk-delete/     → risk_type_bulk_delete_api

  위험 기준 (알람 단계):
    GET  /backoffice/alarm-levels/                   → alarm_level_list
    GET  /backoffice/api/alarm-levels/<pk>/          → alarm_level_detail_api
    POST /backoffice/api/alarm-levels/create/        → alarm_level_create_api
    POST /backoffice/api/alarm-levels/<pk>/update/   → alarm_level_update_api
    POST /backoffice/api/alarm-levels/bulk-delete/   → alarm_level_bulk_delete_api

  임계치:
    GET  /backoffice/thresholds/                     → threshold_manage
    GET  /backoffice/api/threshold-categories/<pk>/  → threshold_cat_detail_api
    POST /backoffice/api/threshold-categories/create/ → threshold_cat_create_api
    POST /backoffice/api/threshold-categories/<pk>/update/ → threshold_cat_update_api
    POST /backoffice/api/thresholds/create/          → threshold_create_api
    POST /backoffice/api/thresholds/<pk>/update/     → threshold_update_api
    POST /backoffice/api/thresholds/bulk-delete/     → threshold_bulk_delete_api
    POST /backoffice/api/thresholds/bulk-toggle/     → threshold_bulk_toggle_api

  FastAPI 동기화:
    GET  /dashboard/api/thresholds/                  → thresholds_for_fastapi
"""
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..forms import (
    CodeGroupForm, CodeForm,
    RiskCategoryForm, RiskTypeForm, AlarmLevelForm,
    ThresholdCategoryForm, ThresholdForm,
)
from ..models import (
    CodeGroup, Code,
    RiskCategory, RiskType, AlarmLevel,
    ThresholdCategory, Threshold,
)
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


# ═══════════════════════════════════════════════════════════
# 공통 코드
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='references')
def code_manage(request):
    """공통 코드 관리 — 그룹 트리 + 그룹별 코드 목록.
    피그마와 동일한 좌(그룹) 우(코드 목록) 2-패널.
    """
    groups = list(CodeGroup.objects.all().order_by('sort_order', 'code'))
    return render(request, 'backoffice/codes/manage.html', {
        'groups': groups,
        'active_menu': 'codes',
    })


def _code_group_to_dict(g: CodeGroup) -> dict:
    return {
        'id': g.id, 'code': g.code, 'name': g.name,
        'description': g.description,
        'sort_order': g.sort_order, 'is_active': g.is_active,
        'is_system': g.is_system,
        'code_count': g.code_count,
        'updated_at': g.updated_at.strftime('%Y-%m-%d %H:%M') if g.updated_at else '-',
        'updated_by_name': g.updated_by.first_name if g.updated_by else '-',
    }

def _code_to_dict(c: Code) -> dict:
    return {
        'id': c.id, 'group_id': c.group_id,
        'code': c.code, 'name': c.name, 'description': c.description,
        'sort_order': c.sort_order, 'is_active': c.is_active,
        'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M') if c.updated_at else '-',
    }


@super_admin_required_api(menu_code='references', action='read')
@require_GET
def code_group_detail_api(request, pk):
    g = get_object_or_404(CodeGroup, pk=pk)
    codes = [_code_to_dict(c) for c in g.codes.order_by('sort_order', 'code')]
    return JsonResponse({'group': _code_group_to_dict(g), 'codes': codes})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def code_group_create_api(request):
    form = CodeGroupForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    g = form.save(by=request.user)
    return JsonResponse({'ok': True, 'group': _code_group_to_dict(g)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def code_group_update_api(request, pk):
    g = get_object_or_404(CodeGroup, pk=pk)
    form = CodeGroupForm(_parse_json(request), instance=g)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    g = form.save(by=request.user)
    return JsonResponse({'ok': True, 'group': _code_group_to_dict(g)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def code_group_delete_api(request, pk):
    g = get_object_or_404(CodeGroup, pk=pk)
    if g.is_system:
        return JsonResponse(
            {'ok': False, 'error': '시스템 코드 그룹은 삭제할 수 없습니다.'},
            status=400,
        )
    g.delete()
    return JsonResponse({'ok': True})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def code_create_api(request):
    form = CodeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    c = form.save(by=request.user)
    return JsonResponse({'ok': True, 'code': _code_to_dict(c)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def code_update_api(request, pk):
    c = get_object_or_404(Code, pk=pk)
    form = CodeForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    c = form.save(by=request.user)
    return JsonResponse({'ok': True, 'code': _code_to_dict(c)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def code_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    deleted, _ = Code.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def code_bulk_toggle_api(request):
    """is_active 일괄 변경. body: {"ids": [...], "is_active": false}"""
    data = _parse_json(request)
    ids = data.get('ids') or []
    target = bool(data.get('is_active'))
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = Code.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({'ok': True, 'updated': n})


# ═══════════════════════════════════════════════════════════
# 위험 유형
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='references')
def risk_manage(request):
    cats = list(RiskCategory.objects.all().order_by('sort_order', 'code'))
    return render(request, 'backoffice/risks/manage.html', {
        'categories': cats,
        'active_menu': 'risks',
    })


def _risk_cat_to_dict(c: RiskCategory) -> dict:
    return {
        'id': c.id, 'code': c.code, 'name': c.name,
        'description': c.description,
        'applies_to': c.applies_to, 'applies_to_list': c.applies_to_list,
        'sort_order': c.sort_order, 'is_active': c.is_active,
        'is_system': c.is_system, 'type_count': c.type_count,
        'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M') if c.updated_at else '-',
        'updated_by_name': c.updated_by.first_name if c.updated_by else '-',
    }

def _risk_type_to_dict(t: RiskType) -> dict:
    return {
        'id': t.id, 'category_id': t.category_id,
        'code': t.code, 'name': t.name, 'description': t.description,
        'show_on_map': t.show_on_map,
        'sort_order': t.sort_order, 'is_active': t.is_active,
        'updated_at': t.updated_at.strftime('%Y-%m-%d %H:%M') if t.updated_at else '-',
    }


@super_admin_required_api(menu_code='references', action='read')
@require_GET
def risk_cat_detail_api(request, pk):
    c = get_object_or_404(RiskCategory, pk=pk)
    types = [_risk_type_to_dict(t) for t in c.types.order_by('sort_order', 'code')]
    return JsonResponse({'category': _risk_cat_to_dict(c), 'types': types})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def risk_cat_create_api(request):
    form = RiskCategoryForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    c = form.save(by=request.user)
    return JsonResponse({'ok': True, 'category': _risk_cat_to_dict(c)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def risk_cat_update_api(request, pk):
    c = get_object_or_404(RiskCategory, pk=pk)
    form = RiskCategoryForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    c = form.save(by=request.user)
    return JsonResponse({'ok': True, 'category': _risk_cat_to_dict(c)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def risk_cat_delete_api(request, pk):
    c = get_object_or_404(RiskCategory, pk=pk)
    if c.is_system:
        return JsonResponse({'ok': False, 'error': '시스템 분류는 삭제할 수 없습니다.'}, status=400)
    c.delete()
    return JsonResponse({'ok': True})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def risk_type_create_api(request):
    form = RiskTypeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    t = form.save(by=request.user)
    return JsonResponse({'ok': True, 'type': _risk_type_to_dict(t)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def risk_type_update_api(request, pk):
    t = get_object_or_404(RiskType, pk=pk)
    form = RiskTypeForm(_parse_json(request), instance=t)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    t = form.save(by=request.user)
    return JsonResponse({'ok': True, 'type': _risk_type_to_dict(t)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def risk_type_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    deleted, _ = RiskType.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


# ═══════════════════════════════════════════════════════════
# 위험 기준 (알람 단계)
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='references')
def alarm_level_list(request):
    rows = list(AlarmLevel.objects.all().order_by('priority', 'code'))
    return render(request, 'backoffice/alarm_levels/list.html', {
        'rows': rows,
        'active_menu': 'alarm_levels',
    })


def _alarm_to_dict(a: AlarmLevel) -> dict:
    return {
        'id': a.id, 'code': a.code, 'name': a.name,
        'color': a.color, 'color_display': a.get_color_display(),
        'intensity': a.intensity, 'intensity_display': a.get_intensity_display(),
        'priority': a.priority, 'description': a.description,
        'is_active': a.is_active, 'is_system': a.is_system,
        'updated_at': a.updated_at.strftime('%Y-%m-%d %H:%M') if a.updated_at else '-',
    }


@super_admin_required_api(menu_code='references', action='read')
@require_GET
def alarm_level_detail_api(request, pk):
    a = get_object_or_404(AlarmLevel, pk=pk)
    return JsonResponse({'alarm_level': _alarm_to_dict(a)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def alarm_level_create_api(request):
    form = AlarmLevelForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    a = form.save(by=request.user)
    return JsonResponse({'ok': True, 'alarm_level': _alarm_to_dict(a)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def alarm_level_update_api(request, pk):
    a = get_object_or_404(AlarmLevel, pk=pk)
    form = AlarmLevelForm(_parse_json(request), instance=a)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    a = form.save(by=request.user)
    return JsonResponse({'ok': True, 'alarm_level': _alarm_to_dict(a)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def alarm_level_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    # 시스템 레벨 보호
    sys_ids = list(
        AlarmLevel.objects.filter(id__in=ids, is_system=True).values_list('id', flat=True)
    )
    if sys_ids:
        return JsonResponse(
            {'ok': False, 'error': f'시스템 단계 {len(sys_ids)}개는 삭제할 수 없습니다.'},
            status=400,
        )
    deleted, _ = AlarmLevel.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


# ═══════════════════════════════════════════════════════════
# 임계치 기준
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='references')
def threshold_manage(request):
    cats = list(ThresholdCategory.objects.all().order_by('sort_order', 'code'))
    return render(request, 'backoffice/thresholds/manage.html', {
        'categories': cats,
        'active_menu': 'thresholds',
    })


def _th_cat_to_dict(c: ThresholdCategory) -> dict:
    return {
        'id': c.id, 'code': c.code, 'name': c.name,
        'description': c.description,
        'applies_to': c.applies_to, 'applies_to_list': c.applies_to_list,
        'sort_order': c.sort_order, 'is_active': c.is_active,
        'is_system': c.is_system, 'threshold_count': c.threshold_count,
        'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M') if c.updated_at else '-',
        'updated_by_name': c.updated_by.first_name if c.updated_by else '-',
    }

def _th_to_dict(t: Threshold) -> dict:
    return {
        'id': t.id, 'category_id': t.category_id,
        'item_code': t.item_code, 'item_name': t.item_name,
        'unit': t.unit,
        'operator': t.operator, 'operator_display': t.get_operator_display(),
        'caution_value': t.caution_value, 'danger_value': t.danger_value,
        'is_active': t.is_active,
        'applies_to': t.applies_to, 'applies_to_list': t.applies_to_list,
        'description': t.description,
        'updated_at': t.updated_at.strftime('%Y-%m-%d %H:%M') if t.updated_at else '-',
    }


@super_admin_required_api(menu_code='references', action='read')
@require_GET
def threshold_cat_detail_api(request, pk):
    c = get_object_or_404(ThresholdCategory, pk=pk)
    items = [_th_to_dict(t) for t in c.thresholds.order_by('item_code')]
    return JsonResponse({'category': _th_cat_to_dict(c), 'thresholds': items})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def threshold_cat_create_api(request):
    form = ThresholdCategoryForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    c = form.save(by=request.user)
    return JsonResponse({'ok': True, 'category': _th_cat_to_dict(c)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def threshold_cat_update_api(request, pk):
    c = get_object_or_404(ThresholdCategory, pk=pk)
    form = ThresholdCategoryForm(_parse_json(request), instance=c)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    c = form.save(by=request.user)
    return JsonResponse({'ok': True, 'category': _th_cat_to_dict(c)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def threshold_create_api(request):
    form = ThresholdForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    t = form.save(by=request.user)
    return JsonResponse({'ok': True, 'threshold': _th_to_dict(t)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def threshold_update_api(request, pk):
    t = get_object_or_404(Threshold, pk=pk)
    form = ThresholdForm(_parse_json(request), instance=t)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    t = form.save(by=request.user)
    return JsonResponse({'ok': True, 'threshold': _th_to_dict(t)})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def threshold_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    deleted, _ = Threshold.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


@super_admin_required_api(menu_code='references', action='write')
@require_POST
def threshold_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get('ids') or []
    target = bool(data.get('is_active'))
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = Threshold.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({'ok': True, 'updated': n})


# ═══════════════════════════════════════════════════════════
# FastAPI 동기화용 내부 API
# ═══════════════════════════════════════════════════════════
#
# /dashboard/api/thresholds/  →  FastAPI 가 호출하여 GAS_THRESHOLDS 대체
#
# 인증: 세션 인증 (Django) 또는 INTERNAL_API_KEY (FastAPI 가 호출 시).
# 응답 포맷: 기존 GAS_THRESHOLDS 와 호환되는 dict 구조 + 추가 메타.

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
    cats = ThresholdCategory.objects.filter(is_active=True).prefetch_related('thresholds')
    payload = {'categories': {}, 'flat': {}}
    for cat in cats:
        cat_obj = {
            'code': cat.code, 'name': cat.name,
            'applies_to': cat.applies_to_list,
            'thresholds': [],
        }
        for t in cat.thresholds.filter(is_active=True):
            entry = {
                'category_code': cat.code,
                'item_code': t.item_code, 'item_name': t.item_name,
                'unit': t.unit, 'operator': t.operator,
                'caution': t.caution_value, 'danger': t.danger_value,
                'applies_to': t.applies_to_list,
            }
            cat_obj['thresholds'].append(entry)
            # flat 은 (category_code, item_code) 조합 키 — 다른 카테고리에 같은 item_code 가 있을 수 있으므로
            payload['flat'][f'{cat.code}.{t.item_code}'] = entry

        payload['categories'][cat.code] = cat_obj

    return JsonResponse(payload)
