"""
backoffice/views/audit.py — v6 감사 로그 조회.

피그마 요구사항 v6 (관제 시스템 변경 추적). audit.py 모듈 (시그널 헬퍼) 과
혼동 주의 — 이 파일은 *뷰* 만 담당. 추적 메커니즘 자체는 ../audit.py 참조.

라우팅:
  GET  /backoffice/audit/                       → audit_log_list (페이지)
  GET  /backoffice/api/devices/<pk>/history/    → device_history_api (모달)
"""
from datetime import datetime, timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET

from devices.models import Device

from ..models import AuditLog, AUDIT_ACTION_CHOICES, DeviceHistory
from ..permissions import super_admin_required, super_admin_required_api


AUDIT_PAGE_SIZE = 30


@super_admin_required(menu_code='operations')
def audit_log_list(request):
    qs = AuditLog.objects.select_related('actor').all()

    q_action = request.GET.get('action', '').strip()
    q_target = request.GET.get('target_model', '').strip()
    q_keyword = request.GET.get('keyword', '').strip()
    q_from = request.GET.get('from', '').strip()
    q_to   = request.GET.get('to', '').strip()

    if q_action:
        qs = qs.filter(action=q_action)
    if q_target:
        qs = qs.filter(target_model=q_target)
    if q_keyword:
        qs = qs.filter(
            Q(actor_username_snapshot__icontains=q_keyword) |
            Q(target_repr__icontains=q_keyword) |
            Q(extra_message__icontains=q_keyword) |
            Q(request_path__icontains=q_keyword)
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
    start = (page - 1) * AUDIT_PAGE_SIZE
    rows = list(qs[start:start + AUDIT_PAGE_SIZE])
    last_page = max(1, (total + AUDIT_PAGE_SIZE - 1) // AUDIT_PAGE_SIZE)

    # 추적 모델 목록 (필터용)
    target_models = list(AuditLog.objects.values_list('target_model', flat=True).distinct().order_by('target_model'))

    return render(request, 'backoffice/audit/log_list.html', {
        'rows': rows,
        'total': total, 'page': page, 'last_page': last_page,
        'page_start': start + 1 if total else 0,
        'page_end': min(start + AUDIT_PAGE_SIZE, total),
        'page_range': range(max(1, page - 4), min(last_page, page + 4) + 1),
        'actions': AUDIT_ACTION_CHOICES,
        'target_models': target_models,
        'q': {'action': q_action, 'target_model': q_target,
              'keyword': q_keyword, 'from': q_from, 'to': q_to},
        'active_menu': 'audit',
    })


@super_admin_required_api(menu_code='devices', action='read')
@require_GET
def device_history_api(request, pk):
    """단일 장비의 변경 이력. 모달 표시용."""
    d = get_object_or_404(Device, pk=pk)
    history = DeviceHistory.objects.filter(device_id_snapshot=d.device_id).order_by('-created_at')[:50]
    return JsonResponse({
        'device': {'id': d.id, 'device_id': d.device_id, 'device_name': d.device_name},
        'history': [{
            'id': h.id, 'action': h.action,
            'action_display': h.get_action_display(),
            'actor': h.actor_username_snapshot or '-',
            'changes': h.changes,
            'message': h.extra_message,
            'created_at': h.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        } for h in history],
    })
