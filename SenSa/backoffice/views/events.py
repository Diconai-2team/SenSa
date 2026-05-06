"""
backoffice/views/events.py — 이벤트 이력 (Alarm) 조회.

피그마 '이벤트 이력 관리' 화면. Alarm 모델 데이터를 검색/필터/정렬/CSV 추출.

라우팅:
  GET  /backoffice/events/                         → event_history (페이지)
  GET  /backoffice/events/csv/                     → event_history_csv
  GET  /backoffice/api/events/<pk>/                → event_detail_api
  POST /backoffice/api/events/bulk-read/           → event_bulk_read_api
"""
import csv
from datetime import datetime, timedelta

from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from alerts.models import Alarm, ALARM_LEVEL_CHOICES, ALARM_TYPE_CHOICES

from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json


EVENT_PAGE_SIZE = 20


def _apply_event_filters(qs, request):
    """검색 조건을 받아 queryset 에 적용. event_history 와 event_history_csv 가 공유."""
    q_level   = request.GET.get('level', '').strip()
    q_type    = request.GET.get('type', '').strip()
    q_keyword = request.GET.get('keyword', '').strip()
    q_from    = request.GET.get('from', '').strip()
    q_to      = request.GET.get('to', '').strip()
    q_unread  = request.GET.get('unread', '').strip()

    if q_level:
        qs = qs.filter(alarm_level=q_level)
    if q_type:
        qs = qs.filter(alarm_type=q_type)
    if q_keyword:
        qs = qs.filter(
            Q(message__icontains=q_keyword) |
            Q(worker_name__icontains=q_keyword) |
            Q(worker_id__icontains=q_keyword) |
            Q(device_id__icontains=q_keyword)
        )
    if q_unread == '1':
        qs = qs.filter(is_read=False)
    if q_from:
        try:
            dt = datetime.strptime(q_from, '%Y-%m-%d')
            qs = qs.filter(created_at__gte=timezone.make_aware(dt))
        except ValueError:
            pass
    if q_to:
        try:
            dt = datetime.strptime(q_to, '%Y-%m-%d') + timedelta(days=1)
            qs = qs.filter(created_at__lt=timezone.make_aware(dt))
        except ValueError:
            pass

    return qs, {
        'level': q_level, 'type': q_type, 'keyword': q_keyword,
        'from': q_from, 'to': q_to, 'unread': q_unread,
    }


@super_admin_required(menu_code='notifications')
def event_history(request):
    """이벤트 이력 조회 페이지 — 검색/필터/정렬/페이지네이션.
    피그마: 알람 발생 일시·레벨·작업자·장비·메시지·읽음 상태 컬럼.
    """
    qs = Alarm.objects.all()
    qs, q = _apply_event_filters(qs, request)

    qs = qs.order_by('-created_at')
    total = qs.count()

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page = 1
    start = (page - 1) * EVENT_PAGE_SIZE
    rows = list(qs[start:start + EVENT_PAGE_SIZE])
    last_page = max(1, (total + EVENT_PAGE_SIZE - 1) // EVENT_PAGE_SIZE)

    return render(request, 'backoffice/events/list.html', {
        'rows': rows,
        'total': total,
        'page': page,
        'last_page': last_page,
        'page_start': start + 1 if total else 0,
        'page_end': min(start + EVENT_PAGE_SIZE, total),
        'page_range': range(max(1, page - 4), min(last_page, page + 4) + 1),
        'levels': ALARM_LEVEL_CHOICES,
        'types': ALARM_TYPE_CHOICES,
        'q': q,
        'active_menu': 'events',
    })


@super_admin_required(menu_code='notifications')
def event_history_csv(request):
    """현재 검색 조건의 이벤트 이력을 CSV 다운로드. 페이지네이션 무시."""
    qs = Alarm.objects.all()
    qs, _ = _apply_event_filters(qs, request)
    qs = qs.order_by('-created_at')

    # CSV 응답 — UTF-8 BOM 으로 Excel 한글 깨짐 방지
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    filename = f"events_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # BOM
    writer = csv.writer(response)
    writer.writerow(['발생일시', '레벨', '유형', '작업자ID', '작업자명', '장비ID', '센서타입', '메시지', '읽음'])
    for a in qs.iterator(chunk_size=500):
        writer.writerow([
            a.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            a.get_alarm_level_display(),
            a.get_alarm_type_display(),
            a.worker_id, a.worker_name,
            a.device_id, a.sensor_type,
            a.message, '읽음' if a.is_read else '안읽음',
        ])
    return response


@super_admin_required_api(menu_code='notifications', action='read')
@require_GET
def event_detail_api(request, pk):
    """이벤트 1건 상세 — 모달용."""
    a = get_object_or_404(Alarm, pk=pk)
    return JsonResponse({'event': {
        'id': a.id,
        'created_at': a.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'alarm_level': a.alarm_level,
        'alarm_level_display': a.get_alarm_level_display(),
        'alarm_type': a.alarm_type,
        'alarm_type_display': a.get_alarm_type_display(),
        'worker_id': a.worker_id, 'worker_name': a.worker_name,
        'worker_x': a.worker_x, 'worker_y': a.worker_y,
        'device_id': a.device_id, 'sensor_type': a.sensor_type,
        'message': a.message,
        'is_read': a.is_read,
        'geofence_name': a.geofence.name if a.geofence else None,
    }})


@super_admin_required_api(menu_code='notifications', action='write')
@require_POST
def event_bulk_read_api(request):
    """선택 이벤트 일괄 읽음 처리."""
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = Alarm.objects.filter(id__in=ids, is_read=False).update(is_read=True)
    return JsonResponse({'ok': True, 'updated': n})
