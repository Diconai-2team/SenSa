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
        return qs[:50]

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
        """
        AI 예측 성능 통계 — GET /dashboard/api/alarm/ai_stats/

        지표 정의:
          TP (True Positive)  = 예측 성공 (실제 임계치 초과 + 예측도 했음)
          FP (False Positive) = 예측 실패 (예측했지만 임계치 미초과)
          FN (False Negative) = 실제 위험 발생했지만 예측 못 함
            = 고정 임계치 초과 알람 건수(is_ai=False) - TP

          Precision = TP / (TP + FP)
          Recall    = TP / (TP + FN)
          F1        = 2 × P × R / (P + R)
          Accuracy  = TP / (TP + FP + FN)
        """
        total   = AIPrediction.objects.count()
        tp      = AIPrediction.objects.filter(result='success').count()  # TP
        fp      = AIPrediction.objects.filter(result='failure').count()  # FP
        pending = AIPrediction.objects.filter(result='pending').count()

        # 실제 위험 발생 건수 — 고정 임계치로 감지된 caution/danger 알람
        # is_ai=False: 고정 임계치 초과 알람 (AI 예측이 아닌 실제 발생)
        actual_danger = Alarm.objects.filter(
            is_ai=False,
            alarm_level__in=['caution', 'danger'],
        ).count()

        # FN = 실제 위험 - AI가 미리 잡은 것
        fn = max(0, actual_danger - tp)

        # 지표 계산
        precision = round(tp / (tp + fp) * 100, 1) if (tp + fp) > 0 else 0
        recall    = round(tp / (tp + fn) * 100, 1) if (tp + fn) > 0 else 0
        f1        = round(
            2 * precision * recall / (precision + recall), 1
        ) if (precision + recall) > 0 else 0
        accuracy  = round(
            tp / (tp + fp + fn) * 100, 1
        ) if (tp + fp + fn) > 0 else 0

        return Response({
            'total':         total,
            'success':       tp,
            'failure':       fp,
            'pending':       pending,
            'actual_danger': actual_danger,
            'fn':            fn,
            'precision':     precision,   # 예측 정확도 (%)
            'recall':        recall,      # 실제 위험 탐지율 (%)
            'f1':            f1,          # F1 점수 (%)
            'accuracy':      accuracy,    # 전체 정확도 (%)
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
        qs = super().get_queryset()
        limit  = int(self.request.query_params.get('limit', 20))
        result = self.request.query_params.get('result')
        if result:
            qs = qs.filter(result=result)
        return qs[:limit]


@login_required(login_url="/accounts/login/")
def alarm_list_view(request):
    level_filter = request.GET.get("level", "all")
    qs = Alarm.objects.all()

    if level_filter == "danger":
        qs = qs.filter(alarm_level__in=["danger", "critical"]).order_by("-created_at")
    elif level_filter == "caution":
        qs = qs.filter(alarm_level="caution").order_by("-created_at")
    elif level_filter == "ai":
        qs = qs.filter(is_ai=True).order_by("-created_at")
    else:
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
    alarms = paginator.get_page(request.GET.get("page", 1))

    since = timezone.now() - timedelta(hours=24)
    stats = {
        "total":    Alarm.objects.count(),
        "danger":   Alarm.objects.filter(alarm_level__in=["danger", "critical"]).count(),
        "caution":  Alarm.objects.filter(alarm_level="caution").count(),
        "ai":       Alarm.objects.filter(is_ai=True).count(),
        "last_24h": Alarm.objects.filter(created_at__gte=since).count(),
    }

    return render(request, "alerts/alarm_list.html", {
        "alarms":       alarms,
        "level_filter": level_filter,
        "stats":        stats,
    })
