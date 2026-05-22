"""
alerts 앱 뷰
"""
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from rest_framework import viewsets, serializers as rf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Alarm, AIPrediction
from .serializers import AlarmSerializer


class AlarmViewSet(viewsets.ReadOnlyModelViewSet):
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
        elif level == "ai":
            qs = qs.filter(is_ai=True)
        # [수정] 슬라이싱을 get_queryset() 안에서 하면 DRF의 get_object()가
        # 내부적으로 .filter(pk=pk)를 호출할 때
        # "Cannot filter a query once a slice has been taken" TypeError 발생.
        # → 슬라이싱은 list 액션에서만 적용하도록 list() 오버라이드로 이동.
        return qs

    def list(self, request, *args, **kwargs):
        """목록 조회 — 최대 50건 제한."""
        queryset = self.filter_queryset(self.get_queryset())[:50]
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        since = timezone.now() - timedelta(hours=24)
        qs = Alarm.objects.filter(created_at__gte=since)
        return Response({
            "danger":  qs.filter(alarm_level__in=["danger", "critical"]).count(),
            "caution": qs.filter(alarm_level="caution").count(),
            "total":   qs.count(),
        })

    @action(detail=True, methods=["patch"])
    def read(self, request, pk=None):
        alarm = self.get_object()
        alarm.is_read = True
        alarm.save()
        return Response({"status": "read", "id": alarm.id})

    @action(detail=False, methods=["patch"])
    def read_all(self, request):
        Alarm.objects.filter(is_read=False).update(is_read=True)
        return Response({"status": "all read"})

    @action(detail=False, methods=["get"])
    def ai_stats(self, request):
        """AI 예측 성능 통계 — GET /dashboard/api/alarm/ai_stats/"""
        total    = AIPrediction.objects.count()
        success  = AIPrediction.objects.filter(result='success').count()
        failure  = AIPrediction.objects.filter(result='failure').count()
        pending  = AIPrediction.objects.filter(result='pending').count()
        accuracy = round(success / (success + failure) * 100, 1) if (success + failure) > 0 else 0
        return Response({
            'total':    total,
            'success':  success,
            'failure':  failure,
            'pending':  pending,
            'accuracy': accuracy,
        })


class AIPredictionSerializer(rf_serializers.ModelSerializer):
    class Meta:
        model  = AIPrediction
        fields = [
            'id', 'device_id', 'sensor_key', 'sensor_type',
            'value_at_predict', 'threshold', 'slope', 'if_score',
            'predicted_ticks', 'predicted_value',
            'result', 'expires_at', 'created_at',
        ]


class AIPredictionViewSet(viewsets.ReadOnlyModelViewSet):
    """AI 예측 기록 조회 — GET /dashboard/api/ai-predictions/"""
    queryset = AIPrediction.objects.all().order_by('-created_at')
    serializer_class = AIPredictionSerializer

    def get_queryset(self):
        # [수정] 슬라이싱을 get_queryset() 에서 하면
        # retrieve(pk=pk) 시 get_object() 의 .filter(pk=pk) 호출이
        # "Cannot filter a query once a slice has been taken" TypeError 로 실패.
        # → 슬라이싱은 list() 오버라이드로 이동.
        qs = super().get_queryset()
        result = self.request.query_params.get('result')
        if result:
            qs = qs.filter(result=result)
        return qs

    def list(self, request, *args, **kwargs):
        """목록 조회 — limit 파라미터 적용."""
        limit = int(self.request.query_params.get('limit', 20))
        queryset = self.filter_queryset(self.get_queryset())[:limit]
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


_ML_ALARM_TYPES = {
    'ai_ml_anomaly', 'ai_anomaly_warning', 'ai_trend_shift',
    'ai_drift_alert', 'ai_predictive_alert', 'ai_predictive_warning', 'ai_correlation',
}
_THRESHOLD_TYPES = {'sensor_danger', 'sensor_caution'}
# 단일 탐지기 알람 타입 (ai_ml_anomaly는 IF 단독 또는 앙상블 양쪽 가능)
_SINGLE_DETECTOR_TYPES = {
    'ai_anomaly_warning', 'ai_trend_shift', 'ai_drift_alert',
    'ai_predictive_alert', 'ai_predictive_warning', 'ai_correlation',
}

# ── 알람 그루핑 ─────────────────────────────────────────────────────────────────
_LEVEL_PRIORITY = {'critical': 0, 'danger': 1, 'caution': 2, 'info': 3}
GROUP_GAP_SECONDS = 600   # 10분 이내 동일 (type, device) = 같은 이벤트로 묶음


def _group_alarms(alarm_qs):
    """
    (alarm_type, device_id) 조합 기준으로 연속 알람을 이벤트 단위로 그루핑.

    - 연속 알람 간 gap < GROUP_GAP_SECONDS(10분) 이면 동일 그룹
    - 그룹 대표 알람: 그룹 내 최고 severity 알람 (메시지 포함)
    - 반환: list of dict { first_alarm, representative, alarms, count,
                           first_at, last_at, alarm_type, device_id, max_level }
    """
    alarms = list(alarm_qs.order_by('created_at'))

    groups = []
    open_groups: dict = {}   # key → group dict

    for alarm in alarms:
        key = (alarm.alarm_type, alarm.device_id or '')

        if key in open_groups:
            g = open_groups[key]
            gap = (alarm.created_at - g['last_at']).total_seconds()
            if gap <= GROUP_GAP_SECONDS:
                g['alarms'].append(alarm)
                g['last_at'] = alarm.created_at
                g['count'] += 1
                # 최고 레벨 알람을 대표로 갱신
                if (_LEVEL_PRIORITY.get(alarm.alarm_level, 99)
                        < _LEVEL_PRIORITY.get(g['max_level'], 99)):
                    g['max_level'] = alarm.alarm_level
                    g['representative'] = alarm
                continue
            else:
                # 갭 초과 → 현재 그룹 확정, 새 그룹 시작
                groups.append(open_groups.pop(key))

        open_groups[key] = {
            'first_alarm':    alarm,   # 첫 발화 (시간순 첫 번째)
            'representative': alarm,   # 최고 severity (갱신됨)
            'alarms':         [alarm],
            'count':          1,
            'first_at':       alarm.created_at,
            'last_at':        alarm.created_at,
            'alarm_type':     alarm.alarm_type,
            'device_id':      alarm.device_id or '',
            'max_level':      alarm.alarm_level,
        }

    groups.extend(open_groups.values())
    # 최신 이벤트 우선
    groups.sort(key=lambda g: g['last_at'], reverse=True)
    return groups


_DEFAULT_DAYS = 7     # 기본 조회 기간 (최근 N일)


@login_required(login_url="/accounts/login/")
def alarm_list_view(request):
    from django.db.models import Exists, OuterRef

    level_filter = request.GET.get("level", "all")

    # 조회 기간 파라미터 (?days=7 기본, ?days=0 → 전체)
    try:
        days = int(request.GET.get("days", _DEFAULT_DAYS))
    except (ValueError, TypeError):
        days = _DEFAULT_DAYS

    since_cutoff = timezone.now() - timedelta(days=days) if days > 0 else None

    # 10분 내 같은 device 임계치 알람이 뒤따랐는지 subquery
    threshold_after = Alarm.objects.filter(
        alarm_type__in=_THRESHOLD_TYPES,
        device_id=OuterRef('device_id'),
        created_at__gt=OuterRef('created_at'),
        created_at__lte=OuterRef('created_at') + timedelta(minutes=10),
    )

    qs = Alarm.objects.annotate(has_threshold_after=Exists(threshold_after))
    if since_cutoff:
        qs = qs.filter(created_at__gte=since_cutoff)

    if level_filter == "danger":
        qs = qs.filter(alarm_level__in=["danger", "critical"])
    elif level_filter == "caution":
        qs = qs.filter(alarm_level="caution")
    elif level_filter == "ai":
        qs = qs.filter(is_ai=True)

    alarm_groups = _group_alarms(qs)
    paginator = Paginator(alarm_groups, 20)
    alarm_page = paginator.get_page(request.GET.get("page", 1))

    since_24h = timezone.now() - timedelta(hours=24)
    stats = {
        "total":    Alarm.objects.count(),
        "danger":   Alarm.objects.filter(alarm_level__in=["danger", "critical"]).count(),
        "caution":  Alarm.objects.filter(alarm_level="caution").count(),
        "ai":       Alarm.objects.filter(is_ai=True).count(),
        "last_24h": Alarm.objects.filter(created_at__gte=since_24h).count(),
    }

    return render(request, "alerts/alarm_list.html", {
        "alarm_groups":          alarm_page,
        "level_filter":          level_filter,
        "days":                  days,
        "stats":                 stats,
        "single_detector_types": _SINGLE_DETECTOR_TYPES,
    })
