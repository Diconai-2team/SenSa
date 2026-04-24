"""
alerts 앱 뷰

- AlarmViewSet: 알람 조회 + 읽음 처리 + 24h 통계
- alarm_list_view: 알람 상세 목록 페이지 (HTML)
"""
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from itertools import groupby

from .models import Alarm
from .serializers import AlarmSerializer


class AlarmViewSet(viewsets.ReadOnlyModelViewSet):
    """알람 조회 / 읽음 처리 / 통계 API"""
    queryset = Alarm.objects.all().order_by("-created_at")
    serializer_class = AlarmSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        level = self.request.query_params.get("level", "")
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
        if level == "danger":
            qs = qs.filter(alarm_level__in=["danger", "critical"])
        elif level in ("caution", "critical", "info"):
            qs = qs.filter(alarm_level=level)
        return qs[:50]

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """최근 24시간 알람 통계 — GET /dashboard/api/alarm/stats/"""
        since = timezone.now() - timedelta(hours=24)
        qs = Alarm.objects.filter(created_at__gte=since)
        return Response({
            "danger":  qs.filter(alarm_level__in=["danger", "critical"]).count(),
            "caution": qs.filter(alarm_level="caution").count(),
            "total":   qs.count(),
        })

    @action(detail=True, methods=["patch"])
    def read(self, request, pk=None):
        """특정 알람 읽음 처리 — PATCH /dashboard/api/alarm/{id}/read/"""
        alarm = self.get_object()
        alarm.is_read = True
        alarm.save()
        return Response({"status": "read", "id": alarm.id})

    @action(detail=False, methods=["patch"])
    def read_all(self, request):
        """전체 알람 읽음 처리 — PATCH /dashboard/api/alarm/read_all/"""
        Alarm.objects.filter(is_read=False).update(is_read=True)
        return Response({"status": "all read"})

def _group_alarms(alarm_list):
    """
    같은 초·같은 레벨의 알람을 한 그룹으로 묶음.
    """
    def key_fn(a):
        return (a.created_at.replace(microsecond=0), a.alarm_level)
    
    # 같은 (초, 레벨) 키끼리 인접하도록 정렬
    # 시간 내림차순(최신이 위) + 같은 초 내에선 레벨 기준
    sorted_list = sorted(alarm_list, key=lambda a: (
        -a.created_at.replace(microsecond=0).timestamp(),
        a.alarm_level,
    ))
    
    groups = []
    for (time, level), items in groupby(sorted_list, key=key_fn):
        items = list(items)
        
        worker_names = []
        device_ids = []
        for a in items:
            if a.worker_name and a.worker_name not in worker_names:
                worker_names.append(a.worker_name)
            if a.device_id and a.device_id not in device_ids:
                device_ids.append(a.device_id)
        
        # 센서 알람이 있으면 대표로 선정
        sensor_alarm = next((a for a in items if a.device_id), None)
        primary = sensor_alarm or items[0]
        
        groups.append({
            'time': time,
            'level': level,
            'count': len(items),
            'is_read': all(a.is_read for a in items),
            'primary': primary,
            'worker_names': worker_names,
            'device_ids': device_ids,
        })
    return groups


@login_required(login_url="/accounts/login/")
def alarm_list_view(request):
    """알람 상세 목록 페이지 — GET /dashboard/alarms/"""
    level_filter = request.GET.get("level", "all")
    qs = Alarm.objects.all().order_by("-created_at")

    if level_filter == "danger":
        qs = qs.filter(alarm_level__in=["danger", "critical"])
    elif level_filter == "caution":
        qs = qs.filter(alarm_level="caution")

    # 전체 쿼리셋을 Python으로 가져와서 그룹핑 → 그룹 단위 페이지네이션
    all_alarms = list(qs)  # DB hit 1회
    all_groups = _group_alarms(all_alarms)
    
    paginator = Paginator(all_groups, 20)
    page_num = request.GET.get("page", 1)
    groups = paginator.get_page(page_num)

    since = timezone.now() - timedelta(hours=24)
    stats = {
        "total":    Alarm.objects.count(),
        "danger":   Alarm.objects.filter(alarm_level__in=["danger", "critical"]).count(),
        "caution":  Alarm.objects.filter(alarm_level="caution").count(),
        "last_24h": Alarm.objects.filter(created_at__gte=since).count(),
    }

    return render(request, "alerts/alarm_list.html", {
        "groups":       groups,
        "level_filter": level_filter,
        "stats":        stats,
    })