"""
backoffice/views/logs.py — 통합 로그 조회 (Log 기능 핵심).

관리·인증 활동(AuditLog) + 시스템 알람(Alarm) + 위험구역 이벤트(ZoneEvent)를
하나의 시간순 타임라인으로 합쳐 검색/필터한다. **신규 모델 없음** — 기존 3개
모델을 공통 형태로 정규화해 보여주는 read-only 조회 레이어.

라우팅:
  GET /backoffice/logs/   → unified_log_list (페이지)

필터: 구분(category) / 키워드(keyword) / 기간(from~to)
"""
from datetime import datetime, timedelta

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from alerts.models import Alarm
from geofence.models import ZoneEvent

from ..models import AuditLog
from ..permissions import super_admin_required

LOG_PAGE_SIZE = 30

# 구분(카테고리) 선택지
CATEGORY_CHOICES = [
    ('activity', '관리·인증 활동'),
    ('alarm', '시스템 알람'),
    ('zone', '위험구역 이벤트'),
]

# 활동(action) → 등급(배지색) 매핑
_ACTIVITY_LEVEL = {
    'create': 'success', 'login': 'success',
    'update': 'caution', 'bulk_op': 'caution', 'csv_upload': 'caution',
    'delete': 'danger', 'login_fail': 'danger',
    'cleanup': 'info', 'dispatch': 'info', 'logout': 'info',
}


def _parse_date(s, *, end=False):
    try:
        dt = datetime.strptime(s, '%Y-%m-%d')
        if end:
            dt += timedelta(days=1)
        return timezone.make_aware(dt)
    except (ValueError, TypeError):
        return None


def _rows_from_audit(dt_from, dt_to, keyword, limit):
    qs = AuditLog.objects.all()
    if dt_from:
        qs = qs.filter(created_at__gte=dt_from)
    if dt_to:
        qs = qs.filter(created_at__lt=dt_to)
    if keyword:
        qs = qs.filter(
            Q(actor_username_snapshot__icontains=keyword)
            | Q(target_repr__icontains=keyword)
            | Q(target_model__icontains=keyword)
            | Q(extra_message__icontains=keyword)
        )
    qs = qs.order_by('-created_at')
    count = qs.count()
    rows = []
    for a in qs[:limit]:
        target = a.target_repr or '-'
        if a.target_pk:
            target = f'#{a.target_pk} — {target}'
        rows.append({
            'when': a.created_at,
            'cat': 'activity', 'cat_label': '관리·인증 활동',
            'action': a.get_action_display(),
            'actor': a.actor_username_snapshot or '-',
            'target': target,
            'sub': a.target_model or '',
            'level': _ACTIVITY_LEVEL.get(a.action, 'info'),
        })
    return rows, count


def _rows_from_alarm(dt_from, dt_to, keyword, limit):
    qs = Alarm.objects.all()
    if dt_from:
        qs = qs.filter(created_at__gte=dt_from)
    if dt_to:
        qs = qs.filter(created_at__lt=dt_to)
    if keyword:
        qs = qs.filter(
            Q(message__icontains=keyword)
            | Q(worker_name__icontains=keyword)
            | Q(device_id__icontains=keyword)
            | Q(sensor_type__icontains=keyword)
        )
    qs = qs.order_by('-created_at')
    count = qs.count()
    rows = []
    for al in qs[:limit]:
        actor = al.worker_name or al.device_id or '-'
        action = al.get_alarm_type_display() if hasattr(al, 'get_alarm_type_display') else al.alarm_type
        if al.is_ai:
            action = f'{action} (AI)'
        rows.append({
            'when': al.created_at,
            'cat': 'alarm', 'cat_label': '시스템 알람',
            'action': action,
            'actor': actor,
            'target': al.message or '-',
            'sub': al.sensor_type or '',
            'level': al.alarm_level or 'info',  # caution/danger/critical
        })
    return rows, count


def _rows_from_zone(dt_from, dt_to, keyword, limit):
    qs = ZoneEvent.objects.select_related('zone').all()
    if dt_from:
        qs = qs.filter(created_at__gte=dt_from)
    if dt_to:
        qs = qs.filter(created_at__lt=dt_to)
    if keyword:
        qs = qs.filter(
            Q(event_type__icontains=keyword)
            | Q(trigger_source__icontains=keyword)
            | Q(zone__name__icontains=keyword)
        )
    qs = qs.order_by('-created_at')
    count = qs.count()
    rows = []
    for z in qs[:limit]:
        zone_name = z.zone.name if z.zone_id else '-'
        tier = ''
        if z.from_tier or z.to_tier:
            tier = f'{z.from_tier or "?"} → {z.to_tier or "?"}'
        # 등급: critical 승격/도달이면 critical, 생성이면 caution, 그 외 info
        if (z.to_tier or '') == 'critical' or z.event_type == 'upgraded_to_critical':
            level = 'critical'
        elif z.event_type == 'created':
            level = 'caution'
        else:
            level = 'info'
        rows.append({
            'when': z.created_at,
            'cat': 'zone', 'cat_label': '위험구역 이벤트',
            'action': z.event_type,
            'actor': z.trigger_source or '-',
            'target': zone_name + (f'  ({tier})' if tier else ''),
            'sub': '',
            'level': level,
        })
    return rows, count


@super_admin_required(menu_code='operations')
@require_GET
def unified_log_list(request):
    q_cat = request.GET.get('cat', '').strip()
    q_keyword = request.GET.get('keyword', '').strip()
    q_from = request.GET.get('from', '').strip()
    q_to = request.GET.get('to', '').strip()

    dt_from = _parse_date(q_from)
    dt_to = _parse_date(q_to, end=True)

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page = 1
    # 전역 상위 (page*size) 행은 각 소스의 상위 (page*size) 행 안에 반드시 포함
    fetch_limit = page * LOG_PAGE_SIZE

    sources = {
        'activity': _rows_from_audit,
        'alarm': _rows_from_alarm,
        'zone': _rows_from_zone,
    }
    if q_cat in sources:
        sources = {q_cat: sources[q_cat]}

    merged, total = [], 0
    for fn in sources.values():
        rows, count = fn(dt_from, dt_to, q_keyword, fetch_limit)
        merged.extend(rows)
        total += count

    # 시간 역순 정렬 후 현재 페이지 슬라이스
    merged.sort(key=lambda r: r['when'], reverse=True)
    start = (page - 1) * LOG_PAGE_SIZE
    rows = merged[start:start + LOG_PAGE_SIZE]
    last_page = max(1, (total + LOG_PAGE_SIZE - 1) // LOG_PAGE_SIZE)

    return render(request, 'backoffice/logs/list.html', {
        'rows': rows,
        'total': total, 'page': page, 'last_page': last_page,
        'page_start': start + 1 if total else 0,
        'page_end': min(start + LOG_PAGE_SIZE, total),
        'page_range': range(max(1, page - 4), min(last_page, page + 4) + 1),
        'categories': CATEGORY_CHOICES,
        'q': {'cat': q_cat, 'keyword': q_keyword, 'from': q_from, 'to': q_to},
        'active_menu': 'logs',
    })
