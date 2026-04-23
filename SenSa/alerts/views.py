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


@login_required(login_url="/accounts/login/")
def alarm_list_view(request):
    """알람 상세 목록 페이지 — GET /dashboard/alarms/"""
    level_filter = request.GET.get("level", "all")
    qs = Alarm.objects.all().order_by("-created_at")

    if level_filter == "danger":
        qs = qs.filter(alarm_level__in=["danger", "critical"])
    elif level_filter == "caution":
        qs = qs.filter(alarm_level="caution")

    paginator = Paginator(qs, 20)
    page_num = request.GET.get("page", 1)
    alarms = paginator.get_page(page_num)

    since = timezone.now() - timedelta(hours=24)
    stats = {
        "total":    Alarm.objects.count(),
        "danger":   Alarm.objects.filter(alarm_level__in=["danger", "critical"]).count(),
        "caution":  Alarm.objects.filter(alarm_level="caution").count(),
        "last_24h": Alarm.objects.filter(created_at__gte=since).count(),
    }

    return render(request, "alerts/alarm_list.html", {
        "alarms":       alarms,
        "level_filter": level_filter,
        "stats":        stats,
    })