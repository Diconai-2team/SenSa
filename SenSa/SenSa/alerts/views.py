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
    """알람 상세 목록 페이지 — GET /dashboard/alarms/

    [통계 카드 개선]
      이전: 전체 / 위험 / 주의 / 최근 24시간 (4개)
            → '전체 = 위험 + 주의' 라는 직관과 어긋남.
              info(회복/복귀) 알람이 큰 비중(약 50%) 인데 카드 어디에도 안 보임.
      현행: 전체 / 위험 / 주의 / 정보 / 최근 24시간 (5개)
            → 전체 = 위험 + 주의 + 정보 가 산술적으로 성립.
              필터 탭에도 '정보' 옵션 추가로 info 알람만 골라보기 가능.

    [정렬 개선]
      이전: 단순 created_at DESC.
            → 누적된 위험 알람이 시간상 과거에 묻혀 '전체' 목록에서 안 보이는 문제.
              데모/시연 시점에 새벽에 발생한 위험 알람 1300여건이 페이지 1에서 누락.
      현행: level=all 일 때만 우선순위 정렬 (critical < danger < caution < info)
            + 같은 레벨 내에서는 created_at DESC.
            → 위험/심각이 항상 상단에 보이고, 새 알람이 추가되면 같은 레벨끼리는
              여전히 최신이 위로 옴. 사용자가 본 "정상 누적" 흐름 유지.
            → 다른 필터(level=danger 등) 에서는 한 레벨만 보이므로 시간순 그대로.
            근거: ISA-18.2 §7 (알람 우선순위) — 위험 알람은 시간보다 우선 노출.
    """
    level_filter = request.GET.get("level", "all")
    qs = Alarm.objects.all()

    if level_filter == "danger":
        # 한 레벨만 보이므로 시간순이 자연스러움
        qs = qs.filter(alarm_level__in=["danger", "critical"]).order_by("-created_at")
    elif level_filter == "caution":
        qs = qs.filter(alarm_level="caution").order_by("-created_at")
    elif level_filter == "info":
        qs = qs.filter(alarm_level="info").order_by("-created_at")
    else:
        # level=all — 위험 우선 + 시간순 (ISA-18.2 §7)
        # critical < danger < caution < info 순으로 위에 오도록 정수 매핑.
        # 그 외 알람 레벨은 99 로 두어 가장 아래.
        from django.db.models import Case, When, IntegerField, Value
        qs = qs.annotate(
            _priority=Case(
                When(alarm_level="critical", then=Value(0)),
                When(alarm_level="danger",   then=Value(1)),
                When(alarm_level="caution",  then=Value(2)),
                When(alarm_level="info",     then=Value(3)),
                default=Value(99),
                output_field=IntegerField(),
            )
        ).order_by("_priority", "-created_at")

    paginator = Paginator(qs, 20)
    page_num = request.GET.get("page", 1)
    alarms = paginator.get_page(page_num)

    since = timezone.now() - timedelta(hours=24)
    stats = {
        "total":    Alarm.objects.count(),
        "danger":   Alarm.objects.filter(alarm_level__in=["danger", "critical"]).count(),
        "caution":  Alarm.objects.filter(alarm_level="caution").count(),
        "info":     Alarm.objects.filter(alarm_level="info").count(),
        "last_24h": Alarm.objects.filter(created_at__gte=since).count(),
    }

    return render(request, "alerts/alarm_list.html", {
        "alarms":       alarms,
        "level_filter": level_filter,
        "stats":        stats,
    })