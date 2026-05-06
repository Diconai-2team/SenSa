"""
backoffice/views/devices.py — 설비/장비 (Device) 관리.

피그마 '설비/장비 관리' 화면. CRUD + 일괄 토글 + Geofence 자동 매핑 + CSV 일괄 업로드.

라우팅:
  GET  /backoffice/devices/                            → device_list
  GET  /backoffice/api/devices/<pk>/                   → device_detail_api
  POST /backoffice/api/devices/create/                 → device_create_api
  POST /backoffice/api/devices/<pk>/update/            → device_update_api
  POST /backoffice/api/devices/bulk-delete/            → device_bulk_delete_api
  POST /backoffice/api/devices/bulk-toggle/            → device_bulk_toggle_api
  POST /backoffice/api/devices/auto-map-geofence/      → device_auto_map_geofence_api
  POST /backoffice/api/devices/csv-upload/             → device_csv_upload_api
"""
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from devices.models import Device, SENSOR_TYPE_CHOICES as DEVICE_SENSOR_TYPE_CHOICES
from geofence.models import GeoFence

from ..forms import DeviceForm
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


DEVICE_PAGE_SIZE = 20


@super_admin_required(menu_code='devices')
def device_list(request):
    qs = Device.objects.select_related('geofence').all()

    q_keyword = request.GET.get('keyword', '').strip()
    q_type    = request.GET.get('type', '').strip()
    q_status  = request.GET.get('status', '').strip()
    q_active  = request.GET.get('active', '').strip()

    if q_keyword:
        qs = qs.filter(Q(device_id__icontains=q_keyword) | Q(device_name__icontains=q_keyword))
    if q_type:
        qs = qs.filter(sensor_type=q_type)
    if q_status:
        qs = qs.filter(status=q_status)
    if q_active == '1':
        qs = qs.filter(is_active=True)
    elif q_active == '0':
        qs = qs.filter(is_active=False)

    qs = qs.order_by('device_id')
    total = qs.count()

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page = 1
    start = (page - 1) * DEVICE_PAGE_SIZE
    rows = list(qs[start:start + DEVICE_PAGE_SIZE])
    last_page = max(1, (total + DEVICE_PAGE_SIZE - 1) // DEVICE_PAGE_SIZE)

    return render(request, 'backoffice/devices/list.html', {
        'rows': rows,
        'total': total,
        'page': page, 'last_page': last_page,
        'page_start': start + 1 if total else 0,
        'page_end': min(start + DEVICE_PAGE_SIZE, total),
        'page_range': range(max(1, page - 4), min(last_page, page + 4) + 1),
        'sensor_types': DEVICE_SENSOR_TYPE_CHOICES,
        'geofences': GeoFence.objects.all().order_by('name'),
        'q': {'keyword': q_keyword, 'type': q_type, 'status': q_status, 'active': q_active},
        'active_menu': 'devices',
    })


def _device_to_dict(d: Device) -> dict:
    return {
        'id': d.id, 'device_id': d.device_id, 'device_name': d.device_name,
        'sensor_type': d.sensor_type,
        'sensor_type_display': d.get_sensor_type_display(),
        'x': d.x, 'y': d.y,
        'status': d.status, 'status_display': d.get_status_display(),
        'last_value': d.last_value, 'last_value_unit': d.last_value_unit,
        'is_active': d.is_active,
        'geofence_id': d.geofence_id,
        'geofence_name': d.geofence.name if d.geofence else None,
    }


@super_admin_required_api(menu_code='devices', action='read')
@require_GET
def device_detail_api(request, pk):
    d = get_object_or_404(Device.objects.select_related('geofence'), pk=pk)
    return JsonResponse({'device': _device_to_dict(d)})


@super_admin_required_api(menu_code='devices', action='write')
@require_POST
def device_create_api(request):
    form = DeviceForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    d = form.save(by=request.user)
    return JsonResponse({'ok': True, 'device': _device_to_dict(d)})


@super_admin_required_api(menu_code='devices', action='write')
@require_POST
def device_update_api(request, pk):
    d = get_object_or_404(Device, pk=pk)
    form = DeviceForm(_parse_json(request), instance=d)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    d = form.save(by=request.user)
    return JsonResponse({'ok': True, 'device': _device_to_dict(d)})


@super_admin_required_api(menu_code='devices', action='write')
@require_POST
def device_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    deleted, _ = Device.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


@super_admin_required_api(menu_code='devices', action='write')
@require_POST
def device_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get('ids') or []
    target = bool(data.get('is_active'))
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = Device.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({'ok': True, 'updated': n})


@super_admin_required_api(menu_code='devices', action='write')
@require_POST
def device_auto_map_geofence_api(request):
    """현재 좌표 기준으로 모든 장비의 geofence 를 자동 매핑.
    기존 매핑이 있어도 강제 재계산.
    """
    from ..geo_utils import find_containing_geofence
    active_fences = list(GeoFence.objects.filter(is_active=True))
    updated = 0
    cleared = 0
    for d in Device.objects.all():
        matched = find_containing_geofence(d.x, d.y, active_fences)
        if matched and d.geofence_id != matched.id:
            d.geofence = matched
            d.save(update_fields=['geofence'])
            updated += 1
        elif not matched and d.geofence_id is not None:
            d.geofence = None
            d.save(update_fields=['geofence'])
            cleared += 1
    return JsonResponse({'ok': True, 'mapped': updated, 'cleared': cleared})


@super_admin_required_api(menu_code='devices', action='write')
@require_POST
def device_csv_upload_api(request):
    """CSV 일괄 등록.

    [v6] mode=create (default) | upsert + DeviceHistory 자동 기록.
    형식: device_id,device_name,sensor_type,x,y,is_active,last_value_unit
    """
    if 'file' not in request.FILES:
        return JsonResponse({'ok': False, 'error': '파일이 첨부되지 않았습니다.'}, status=400)
    f = request.FILES['file']
    if f.size > 5 * 1024 * 1024:
        return JsonResponse({'ok': False, 'error': '파일 크기는 5MB 이하여야 합니다.'}, status=400)

    mode = (request.POST.get('mode') or 'create').strip().lower()
    if mode not in ('create', 'upsert'):
        return JsonResponse({'ok': False, 'error': "mode 는 'create' 또는 'upsert' 여야 합니다."}, status=400)

    try:
        text = f.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return JsonResponse({'ok': False, 'error': 'UTF-8 로 인코딩된 CSV 파일이어야 합니다.'}, status=400)

    import csv as _csv, io as _io
    reader = _csv.DictReader(_io.StringIO(text))
    if reader.fieldnames and reader.fieldnames[0].startswith('\ufeff'):
        reader.fieldnames[0] = reader.fieldnames[0][1:]
    required = {'device_id', 'device_name', 'sensor_type', 'x', 'y'}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        return JsonResponse({
            'ok': False,
            'error': f'필수 컬럼이 빠졌습니다: {sorted(required - set(reader.fieldnames or []))}',
        }, status=400)

    valid_types = {c[0] for c in DEVICE_SENSOR_TYPE_CHOICES}
    created, updated, skipped, errors = 0, 0, 0, []
    existing_by_id = {d.device_id: d for d in Device.objects.all()}

    from ..geo_utils import find_containing_geofence
    from ..audit import write_device_history
    active_fences = list(GeoFence.objects.filter(is_active=True))

    for line_no, row in enumerate(reader, start=2):
        device_id = (row.get('device_id') or '').strip()
        device_name = (row.get('device_name') or '').strip()
        sensor_type = (row.get('sensor_type') or '').strip()
        try:
            x = float(row.get('x', 0)); y = float(row.get('y', 0))
        except ValueError:
            errors.append({'line': line_no, 'error': '좌표가 숫자가 아닙니다.'})
            continue
        is_active_raw = (row.get('is_active') or '').strip().lower()
        is_active = is_active_raw in ('1', 'true', 'on', 'yes', 'y', '활성')
        unit = (row.get('last_value_unit') or '').strip()

        if not device_id:
            errors.append({'line': line_no, 'error': 'device_id 누락'})
            continue
        if not device_name:
            errors.append({'line': line_no, 'error': 'device_name 누락'})
            continue
        if sensor_type not in valid_types:
            errors.append({'line': line_no, 'error': f'유효하지 않은 sensor_type: {sensor_type}'})
            continue

        existing = existing_by_id.get(device_id)
        matched = find_containing_geofence(x, y, active_fences)

        if existing:
            if mode == 'create':
                skipped += 1
                continue
            # upsert — 변경 내역 추적
            changes = {}
            if existing.device_name != device_name:
                changes['device_name'] = [existing.device_name, device_name]
                existing.device_name = device_name
            if existing.sensor_type != sensor_type:
                changes['sensor_type'] = [existing.sensor_type, sensor_type]
                existing.sensor_type = sensor_type
            if existing.x != x or existing.y != y:
                changes['xy'] = [[existing.x, existing.y], [x, y]]
                existing.x = x; existing.y = y
            if existing.is_active != is_active:
                changes['is_active'] = [existing.is_active, is_active]
                existing.is_active = is_active
            if unit and existing.last_value_unit != unit:
                changes['last_value_unit'] = [existing.last_value_unit, unit]
                existing.last_value_unit = unit
            if matched and existing.geofence_id != matched.id:
                changes['geofence'] = [existing.geofence.name if existing.geofence else None, matched.name]
                existing.geofence = matched
            if changes:
                existing.save()
                write_device_history(existing, 'csv_import', changes=changes, message=f'CSV upsert (line {line_no})')
                updated += 1
            else:
                skipped += 1
        else:
            d = Device.objects.create(
                device_id=device_id, device_name=device_name,
                sensor_type=sensor_type, x=x, y=y,
                is_active=is_active,
                last_value_unit=unit,
                geofence=matched,
            )
            existing_by_id[device_id] = d
            write_device_history(d, 'csv_import', message=f'CSV 신규 등록 (line {line_no})')
            created += 1

    return JsonResponse({
        'ok': True,
        'mode': mode,
        'created': created, 'updated': updated, 'skipped': skipped,
        'error_count': len(errors),
        'errors': errors[:50],
    })
