"""
backoffice/views/maps.py — 지도 관련 (지오펜스 + 평면도 이미지).

2개 도메인이 모두 menu_code='maps' 권한을 공유하고 같은 화면 영역에서 작동:
  - 지도 편집 (GeoFence + Device 통합 편집) — 피그마 '지도 편집 관리'
  - 평면도 이미지 (MapImage) — v7 신규 (4차에 추가)

라우팅:
  지도 편집:
    GET  /backoffice/maps/                          → map_edit
    GET  /backoffice/api/geofences/<pk>/            → geofence_detail_api
    POST /backoffice/api/geofences/create/          → geofence_create_api
    POST /backoffice/api/geofences/<pk>/update/     → geofence_update_api
    POST /backoffice/api/geofences/<pk>/delete/     → geofence_delete_api

  평면도 이미지 (v7):
    GET  /backoffice/maps/images/                   → map_image_list
    POST /backoffice/api/map-images/create/         → map_image_create_api
    POST /backoffice/api/map-images/<pk>/update/    → map_image_update_api
    POST /backoffice/api/map-images/<pk>/delete/    → map_image_delete_api
    POST /backoffice/api/map-images/<pk>/toggle/    → map_image_toggle_active_api
"""
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from dashboard.models import MapImage
from devices.models import Device
from geofence.models import GeoFence, ZONE_TYPE_CHOICES, RISK_LEVEL_CHOICES

from ..forms import GeoFenceForm, MapImageForm
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


# ═══════════════════════════════════════════════════════════
# 지도 편집 (지오펜스 + 장비 통합 화면)
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='maps')
def map_edit(request):
    """지도 + 지오펜스 + 장비 통합 편집 화면.
    피그마: 좌측 캔버스 (지도 + 지오펜스 폴리곤 + 장비 마커),
    우측 패널 (지오펜스 목록·등록·수정).
    """
    active_map = MapImage.objects.filter(is_active=True).first() or MapImage.objects.first()
    # 평면도 레코드는 있지만 실제 이미지 파일이 없는 orphan 케이스 방어
    if active_map and not active_map.image:
        active_map = None
    geofences = list(GeoFence.objects.all().order_by('-created_at'))
    devices_with_geo = list(Device.objects.filter(is_active=True).select_related('geofence'))
    return render(request, 'backoffice/maps/edit.html', {
        'active_map': active_map,
        'geofences': geofences,
        'devices': devices_with_geo,
        'maps': MapImage.objects.all().order_by('-uploaded_at'),
        'zone_types': ZONE_TYPE_CHOICES,
        'risk_levels': RISK_LEVEL_CHOICES,
        'active_menu': 'maps',
    })


def _gf_to_dict(g: GeoFence) -> dict:
    return {
        'id': g.id, 'name': g.name,
        'zone_type': g.zone_type, 'zone_type_display': g.get_zone_type_display(),
        'risk_level': g.risk_level, 'risk_level_display': g.get_risk_level_display(),
        'description': g.description,
        'polygon': g.polygon,
        'is_active': g.is_active,
        'device_count': g.devices.count(),
        'created_at': g.created_at.strftime('%Y-%m-%d %H:%M') if g.created_at else '-',
    }


@super_admin_required_api(menu_code='maps', action='read')
@require_GET
def geofence_detail_api(request, pk):
    g = get_object_or_404(GeoFence, pk=pk)
    return JsonResponse({'geofence': _gf_to_dict(g)})


@super_admin_required_api(menu_code='maps', action='write')
@require_POST
def geofence_create_api(request):
    form = GeoFenceForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    g = form.save()
    return JsonResponse({'ok': True, 'geofence': _gf_to_dict(g)})


@super_admin_required_api(menu_code='maps', action='write')
@require_POST
def geofence_update_api(request, pk):
    g = get_object_or_404(GeoFence, pk=pk)
    form = GeoFenceForm(_parse_json(request), instance=g)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    g = form.save()
    return JsonResponse({'ok': True, 'geofence': _gf_to_dict(g)})


@super_admin_required_api(menu_code='maps', action='write')
@require_POST
def geofence_delete_api(request, pk):
    g = get_object_or_404(GeoFence, pk=pk)
    # 소속 device 의 geofence FK 는 SET_NULL 로 자동 풀림
    g.delete()
    return JsonResponse({'ok': True})


# ═══════════════════════════════════════════════════════════
# 평면도 이미지 (MapImage) — v7
# ═══════════════════════════════════════════════════════════

def _map_image_to_dict(m: MapImage) -> dict:
    """MapImage 객체를 JSON 응답용 dict 로 직렬화."""
    return {
        'id': m.id,
        'name': m.name,
        'image_url': m.image.url if m.image else '',
        'width': m.width,
        'height': m.height,
        'sort_order': m.sort_order,
        'is_active': m.is_active,
        'uploaded_at': m.uploaded_at.strftime('%Y-%m-%d %H:%M') if m.uploaded_at else '',
    }


def _map_image_in_use_count(m: MapImage) -> int:
    """이 평면도를 사용 중인 장비/지오펜스 카운트.
    Phase 2 에서 Device/GeoFence 에 map_image FK 추가 후 동작."""
    cnt = 0
    try:
        cnt += Device.objects.filter(map_image=m).count()
    except Exception:
        pass
    try:
        cnt += GeoFence.objects.filter(map_image=m).count()
    except Exception:
        pass
    return cnt


@super_admin_required(menu_code='maps')
def map_image_list(request):
    """평면도 이미지 목록 페이지."""
    images = MapImage.objects.all()
    return render(request, 'backoffice/maps/images_list.html', {
        'active_menu': 'maps',
        'active_submenu': 'images',
        'images': images,
        'total': images.count(),
        'active_count': images.filter(is_active=True).count(),
    })


@super_admin_required_api(menu_code='maps', action='write')
@require_POST
def map_image_create_api(request):
    """평면도 이미지 신규 등록."""
    form = MapImageForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    obj = form.save()
    return JsonResponse({'ok': True, 'image': _map_image_to_dict(obj)})


@super_admin_required_api(menu_code='maps', action='write')
@require_POST
def map_image_update_api(request, pk):
    """평면도 이미지 수정 (이미지 파일 교체는 선택)."""
    obj = get_object_or_404(MapImage, pk=pk)
    form = MapImageForm(request.POST, request.FILES, instance=obj)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    obj = form.save()
    return JsonResponse({'ok': True, 'image': _map_image_to_dict(obj)})


@super_admin_required_api(menu_code='maps', action='write')
@require_POST
def map_image_delete_api(request, pk):
    """평면도 이미지 삭제 (사용 중이거나 마지막 활성이면 거부)."""
    obj = get_object_or_404(MapImage, pk=pk)

    # 1) 사용 중인 장비/지오펜스 체크
    in_use = _map_image_in_use_count(obj)
    if in_use > 0:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': [f'이 평면도를 사용 중인 장비/지역이 {in_use}건 있어 삭제할 수 없습니다.']},
        }, status=400)

    # 2) 활성 상태인 마지막 1장은 삭제 거부 (대시보드 보호)
    if obj.is_active and MapImage.objects.filter(is_active=True).count() <= 1:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': ['활성 상태인 마지막 평면도는 삭제할 수 없습니다.']},
        }, status=400)

    name = obj.name
    obj.delete()
    return JsonResponse({'ok': True, 'message': f'"{name}" 평면도가 삭제되었습니다.'})


@super_admin_required_api(menu_code='maps', action='write')
@require_POST
def map_image_toggle_active_api(request, pk):
    """평면도 이미지 활성/비활성 토글."""
    obj = get_object_or_404(MapImage, pk=pk)

    # 마지막 1장 비활성화 거부
    if obj.is_active and MapImage.objects.filter(is_active=True).count() <= 1:
        return JsonResponse({
            'ok': False,
            'errors': {'_form': ['활성 상태인 마지막 평면도는 비활성화할 수 없습니다.']},
        }, status=400)

    obj.is_active = not obj.is_active
    obj.save(update_fields=['is_active'])
    return JsonResponse({'ok': True, 'is_active': obj.is_active})
