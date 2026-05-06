"""
backoffice/views/positions.py — 직위 관리.

라우팅:
  GET  /backoffice/positions/                      → position_list (페이지)
  GET  /backoffice/api/positions/<pk>/             → position_detail_api
  POST /backoffice/api/positions/create/           → position_create_api
  POST /backoffice/api/positions/<pk>/update/      → position_update_api
  POST /backoffice/api/positions/bulk-delete/      → position_bulk_delete_api
"""
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from ..forms import PositionForm
from ..models import Position
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


@super_admin_required(menu_code='users')
def position_list(request):
    q = request.GET.get('q', '').strip()
    qs = Position.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
    qs = qs.order_by('sort_order', 'name')
    return render(request, 'backoffice/positions/list.html', {
        'rows' : list(qs),
        'q'    : q,
    })


def _position_to_dict(p: Position) -> dict:
    return {
        'id'        : p.id,
        'name'      : p.name,
        'sort_order': p.sort_order,
        'is_active' : p.is_active,
        'description': p.description,
        'updated_at': p.updated_at.strftime('%Y-%m-%d %H:%M') if p.updated_at else '-',
    }


@super_admin_required_api(menu_code='users', action='read')
@require_GET
def position_detail_api(request, pk):
    p = get_object_or_404(Position, pk=pk)
    return JsonResponse({'position': _position_to_dict(p)})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def position_create_api(request):
    form = PositionForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse(
            {'ok': False, 'errors': _form_errors_payload(form)},
            status=400,
        )
    p = form.save(by=request.user)
    return JsonResponse({'ok': True, 'position': _position_to_dict(p)})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def position_update_api(request, pk):
    p = get_object_or_404(Position, pk=pk)
    form = PositionForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse(
            {'ok': False, 'errors': _form_errors_payload(form)},
            status=400,
        )
    p = form.save(by=request.user)
    return JsonResponse({'ok': True, 'position': _position_to_dict(p)})


@super_admin_required_api(menu_code='users', action='write')
@require_POST
def position_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    deleted, _ = Position.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})
