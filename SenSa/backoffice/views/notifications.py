"""
backoffice/views/notifications.py — 알림 관련 3개 도메인.

3개 도메인을 한 모듈로 묶음 (모두 알림 시스템의 일부, 권한도 인접):
  - 알림 정책 (NotificationPolicy)  — menu_code='notifications'
  - 알림 발송 이력 (NotificationLog) — menu_code='notifications'
  - 메뉴 권한 (MenuPermission)       — menu_code='menus'

라우팅:
  알림 정책:
    GET  /backoffice/notification-policies/             → notification_policy_list
    GET  /backoffice/api/notification-policies/<pk>/    → policy_detail_api
    POST /backoffice/api/notification-policies/create/  → policy_create_api
    POST /backoffice/api/notification-policies/<pk>/update/ → policy_update_api
    POST /backoffice/api/notification-policies/bulk-delete/ → policy_bulk_delete_api
    POST /backoffice/api/notification-policies/bulk-toggle/ → policy_bulk_toggle_api

  알림 발송 이력:
    GET  /backoffice/notification-logs/                 → notification_log_list

  메뉴 권한:
    GET  /backoffice/menus/                             → menu_management
    POST /backoffice/api/menus/perm-update/             → menu_perm_update_api
"""
from datetime import datetime, timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from ..forms import NotificationPolicyForm, MenuPermissionUpdateForm
from ..models import (
    NotificationPolicy, NotificationLog, MenuPermission,
    AlarmLevel, RiskCategory, Organization,
    NOTIFICATION_CHANNEL_CHOICES, MENU_CODE_CHOICES,
)
from ..permissions import super_admin_required, super_admin_required_api
from ._common import _parse_json, _form_errors_payload


# ═══════════════════════════════════════════════════════════
# 알림 정책
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='notifications')
def notification_policy_list(request):
    rows = list(NotificationPolicy.objects.select_related('risk_category', 'alarm_level').all())
    return render(request, 'backoffice/notifications/policy_list.html', {
        'rows': rows,
        'risk_categories': RiskCategory.objects.filter(is_active=True),
        'alarm_levels': AlarmLevel.objects.filter(is_active=True).order_by('priority'),
        'organizations': Organization.objects.filter(parent__isnull=False, is_unassigned_bucket=False),
        'channel_choices': NOTIFICATION_CHANNEL_CHOICES,
        'active_menu': 'notification_policies',
    })


def _policy_to_dict(p: NotificationPolicy) -> dict:
    return {
        'id': p.id, 'code': p.code, 'name': p.name,
        'description': p.description,
        'risk_category_id': p.risk_category_id,
        'risk_category_name': p.risk_category.name,
        'alarm_level_id': p.alarm_level_id,
        'alarm_level_name': p.alarm_level.name,
        'channels_csv': p.channels_csv, 'channels_list': p.channels_list,
        'recipients_csv': p.recipients_csv, 'recipients_list': p.recipients_list,
        'message_template': p.message_template,
        'sort_order': p.sort_order, 'is_active': p.is_active,
        'updated_at': p.updated_at.strftime('%Y-%m-%d %H:%M') if p.updated_at else '-',
    }


@super_admin_required_api(menu_code='notifications', action='read')
@require_GET
def policy_detail_api(request, pk):
    p = get_object_or_404(
        NotificationPolicy.objects.select_related('risk_category', 'alarm_level'),
        pk=pk,
    )
    return JsonResponse({'policy': _policy_to_dict(p)})


@super_admin_required_api(menu_code='notifications', action='write')
@require_POST
def policy_create_api(request):
    form = NotificationPolicyForm(_parse_json(request))
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    p = form.save(by=request.user)
    return JsonResponse({'ok': True, 'policy': _policy_to_dict(p)})


@super_admin_required_api(menu_code='notifications', action='write')
@require_POST
def policy_update_api(request, pk):
    p = get_object_or_404(NotificationPolicy, pk=pk)
    form = NotificationPolicyForm(_parse_json(request), instance=p)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    p = form.save(by=request.user)
    return JsonResponse({'ok': True, 'policy': _policy_to_dict(p)})


@super_admin_required_api(menu_code='notifications', action='write')
@require_POST
def policy_bulk_delete_api(request):
    ids = _parse_json(request).get('ids') or []
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    deleted, _ = NotificationPolicy.objects.filter(id__in=ids).delete()
    return JsonResponse({'ok': True, 'deleted': deleted})


@super_admin_required_api(menu_code='notifications', action='write')
@require_POST
def policy_bulk_toggle_api(request):
    data = _parse_json(request)
    ids = data.get('ids') or []
    target = bool(data.get('is_active'))
    if not ids:
        return JsonResponse({'ok': False, 'error': '대상 없음'}, status=400)
    n = NotificationPolicy.objects.filter(id__in=ids).update(is_active=target)
    return JsonResponse({'ok': True, 'updated': n})


# ═══════════════════════════════════════════════════════════
# 알림 발송 이력
# ═══════════════════════════════════════════════════════════

NOTIF_LOG_PAGE_SIZE = 30


@super_admin_required(menu_code='notifications')
def notification_log_list(request):
    qs = NotificationLog.objects.select_related('policy', 'recipient', 'alarm').all()

    q_status   = request.GET.get('status', '').strip()
    q_channel  = request.GET.get('channel', '').strip()
    q_keyword  = request.GET.get('keyword', '').strip()
    q_from     = request.GET.get('from', '').strip()
    q_to       = request.GET.get('to', '').strip()

    if q_status:
        qs = qs.filter(send_status=q_status)
    if q_channel:
        qs = qs.filter(channel=q_channel)
    if q_keyword:
        qs = qs.filter(
            Q(recipient_name_snapshot__icontains=q_keyword) |
            Q(error_message__icontains=q_keyword) |
            Q(policy__name__icontains=q_keyword)
        )
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

    qs = qs.order_by('-created_at')
    total = qs.count()

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page = 1
    start = (page - 1) * NOTIF_LOG_PAGE_SIZE
    rows = list(qs[start:start + NOTIF_LOG_PAGE_SIZE])
    last_page = max(1, (total + NOTIF_LOG_PAGE_SIZE - 1) // NOTIF_LOG_PAGE_SIZE)

    # 통계 (전체 + 24시간)
    since_24h = timezone.now() - timedelta(hours=24)
    stats_24h = NotificationLog.objects.filter(created_at__gte=since_24h)
    stats = {
        'total':   total,
        'sent_24h':    stats_24h.filter(send_status='sent').count(),
        'failed_24h':  stats_24h.filter(send_status='failed').count(),
        'pending_24h': stats_24h.filter(send_status='pending').count(),
    }

    return render(request, 'backoffice/notifications/log_list.html', {
        'rows': rows,
        'total': total, 'stats': stats,
        'page': page, 'last_page': last_page,
        'page_start': start + 1 if total else 0,
        'page_end': min(start + NOTIF_LOG_PAGE_SIZE, total),
        'page_range': range(max(1, page - 4), min(last_page, page + 4) + 1),
        'channel_choices': NOTIFICATION_CHANNEL_CHOICES,
        'status_choices': NotificationLog.SEND_STATUS_CHOICES,
        'q': {'status': q_status, 'channel': q_channel, 'keyword': q_keyword, 'from': q_from, 'to': q_to},
        'active_menu': 'notification_logs',
    })


# ═══════════════════════════════════════════════════════════
# 메뉴 권한
# ═══════════════════════════════════════════════════════════

@super_admin_required(menu_code='menus')
def menu_management(request):
    """역할 ↔ 메뉴 매트릭스. super_admin 은 항상 전체.
    admin 만 토글 가능.
    """
    perms = MenuPermission.objects.filter(role='admin')
    perm_map = {p.menu_code: p for p in perms}
    rows = []
    for code, label in MENU_CODE_CHOICES:
        p = perm_map.get(code)
        rows.append({
            'menu_code': code, 'menu_name': label,
            'is_visible': p.is_visible if p else False,
            'is_writable': p.is_writable if p else False,
            'updated_at': p.updated_at.strftime('%Y-%m-%d %H:%M') if p and p.updated_at else '-',
        })
    return render(request, 'backoffice/menus/manage.html', {
        'rows': rows,
        'active_menu': 'menus',
    })


@super_admin_required_api(menu_code='menus', action='write')
@require_POST
def menu_perm_update_api(request):
    """단일 권한 토글. body: {role, menu_code, is_visible, is_writable}"""
    data = _parse_json(request)
    form = MenuPermissionUpdateForm(data)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': _form_errors_payload(form)}, status=400)
    role = form.cleaned_data['role']
    menu_code = form.cleaned_data['menu_code']

    p, _ = MenuPermission.objects.get_or_create(role=role, menu_code=menu_code)
    # 명시적 토글 - is_writable 은 is_visible 일 때만 의미가 있어 강제
    is_visible = bool(data.get('is_visible'))
    is_writable = bool(data.get('is_writable')) and is_visible
    p.is_visible = is_visible
    p.is_writable = is_writable
    p.updated_by = request.user
    p.save()
    return JsonResponse({'ok': True, 'perm': {
        'role': p.role, 'menu_code': p.menu_code,
        'is_visible': p.is_visible, 'is_writable': p.is_writable,
        'updated_at': p.updated_at.strftime('%Y-%m-%d %H:%M'),
    }})
