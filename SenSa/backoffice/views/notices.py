"""
backoffice/views/notices.py — 공지사항 (Notice) 관리.

피그마 '공지사항 관리' 화면. CRUD + 일괄 토글 + 사용자 알림 발송.

라우팅:
  GET  /backoffice/notices/                          → notice_list
  GET  /backoffice/api/notices/<pk>/                 → notice_detail_api
  POST /backoffice/api/notices/create/               → notice_create_api
  POST /backoffice/api/notices/<pk>/update/          → notice_update_api
  POST /backoffice/api/notices/<pk>/dispatch/        → notice_dispatch_api
  POST /backoffice/api/notices/bulk-delete/          → notice_bulk_delete_api
  POST /backoffice/api/notices/bulk-toggle/          → notice_bulk_toggle_api
"""
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from ..forms import NoticeForm
from ..models import Notice, NOTICE_CATEGORY_CHOICES
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


NOTICE_PAGE_SIZE = 20


@super_admin_required(menu_code='notices')
def notice_list(request):
    qs = Notice.objects.all()

    q_keyword = request.GET.get('keyword', '').strip()
    q_category = request.GET.get('category', '').strip()
    q_published = request.GET.get('published', '').strip()

    if q_keyword:
        qs = qs.filter(Q(title__icontains=q_keyword) | Q(content__icontains=q_keyword))
    if q_category:
        qs = qs.filter(category=q_category)
    if q_published == '1':
        qs = qs.filter(is_published=True)
    elif q_published == '0':
        qs = qs.filter(is_published=False)

    qs = qs.order_by('-is_pinned', '-created_at')
    total = qs.count()

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page = 1
    start = (page - 1) * NOTICE_PAGE_SIZE
    rows = list(qs[start:start + NOTICE_PAGE_SIZE])
    last_page = max(1, (total + NOTICE_PAGE_SIZE - 1) // NOTICE_PAGE_SIZE)

    return render(request, 'backoffice/notices/list.html', {
        'rows': rows,
        'total': total, 'page': page, 'last_page': last_page,
        'page_start': start + 1 if total else 0,
        'page_end': min(start + NOTICE_PAGE_SIZE, total),
        'page_range': range(max(1, page - 4), min(last_page, page + 4) + 1),
        'categories': NOTICE_CATEGORY_CHOICES,
        'q': {'keyword': q_keyword, 'category': q_category, 'published': q_published},
        'active_menu': 'notices',
    })


def _notice_to_dict(n: Notice) -> dict:
    return {
        'id': n.id, 'title': n.title,
        'category': n.category, 'category_display': n.get_category_display(),
        'content': n.content,
        'is_pinned': n.is_pinned,
        'is_published': n.is_published,
        'published_from': n.published_from.strftime('%Y-%m-%dT%H:%M') if n.published_from else None,
        'published_to': n.published_to.strftime('%Y-%m-%dT%H:%M') if n.published_to else None,
        'view_count': n.view_count,
        'created_at': n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else '-',
        'created_by_name': n.created_by.first_name if n.created_by else '-',
    }


@super_admin_required_api(menu_code='notices', action='read')
@require_GET
def notice_detail_api(request, pk):
    n = get_object_or_404(Notice, pk=pk)
    return JsonResponse({'notice': _notice_to_dict(n)})


@super_admin_required_api(menu_code='notices', action='write')
@require_POST
def notice_create_api(request):
    form = NoticeForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    n = form.save(by=request.user)

    # v5 — 게시 + send_notify 옵션 시 즉시 발송
    payload = _parse_json(request)
    if payload.get('send_notify') and n.is_published:
        from ..notification_dispatcher import dispatch_for_notice
        try:
            dispatched = dispatch_for_notice(n)
            return JsonResponse({'ok': True, 'notice': _notice_to_dict(n), 'dispatched': dispatched})
        except Exception as e:
            # 알림 발송 실패는 공지 등록 자체엔 영향 없음
            return JsonResponse({'ok': True, 'notice': _notice_to_dict(n), 'notify_error': str(e)})

    return JsonResponse({'ok': True, 'notice': _notice_to_dict(n)})


@super_admin_required_api(menu_code='notices', action='write')
@require_POST
def notice_dispatch_api(request, pk):
    """기존 공지를 수동으로 사용자에게 알림 발송."""
    n = get_object_or_404(Notice, pk=pk)
    if not n.is_published:
        return JsonResponse({'ok': False, 'error': '미게시 공지는 발송할 수 없습니다.'}, status=400)
    from ..notification_dispatcher import dispatch_for_notice
    channels = _parse_json(request).get('channels') or ['app', 'realtime']
    dispatched = dispatch_for_notice(n, channels=channels)
    return JsonResponse({'ok': True, 'dispatched': dispatched})


@super_admin_required_api(menu_code='notices', action='write')
@require_POST
def notice_update_api(request, pk):
    n = get_object_or_404(Notice, pk=pk)
    form = NoticeForm(_parse_json(request), instance=n)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    n = form.save(by=request.user)
    return JsonResponse({'ok': True, 'notice': _notice_to_dict(n)})


@super_admin_required_api(menu_code='notices', action='write')
@require_POST
def notice_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    deleted, _ = Notice.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


@super_admin_required_api(menu_code='notices', action='write')
@require_POST
def notice_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get('ids') or []
    target = bool(data.get('is_published'))
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = Notice.objects.filter(id__in=ids).update(is_published=target)
    return JsonResponse({'ok': True, 'updated': n})
