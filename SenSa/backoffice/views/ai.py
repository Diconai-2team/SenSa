"""
backoffice/views/ai.py — AI 탐지 모델 성능 지표 대시보드.

라우팅:
  GET  /backoffice/ai-metrics/          → ai_metrics_view
  GET  /backoffice/api/eval-metrics/    → eval_metrics_api
"""
from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from alerts.models import Alarm
from ..permissions import super_admin_required


_AI_ALARM_LABELS = {
    'ai_ml_anomaly':         'AI ML 이상',
    'ai_anomaly_warning':    'AI 통계 이상',
    'ai_trend_shift':        'AI 급변 탐지',
    'ai_predictive_alert':   'AI 예측 위험',
    'ai_predictive_warning': 'AI 예측 주의',
    'ai_drift_alert':        'AI 드리프트',
    'ai_correlation':        'AI 상관관계',
}


@super_admin_required(menu_code='ai_metrics')
def ai_metrics_view(request):
    """AI 탐지 모델 성능 지표 페이지 — /backoffice/ai-metrics/"""
    from django.db.models import Count, Max, Q

    now      = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d  = now - timedelta(days=7)

    ai_qs = Alarm.objects.filter(alarm_type__startswith='ai_')

    # 요약 카드
    summary = ai_qs.aggregate(
        total_all=Count('id'),
        total_24h=Count('id', filter=Q(created_at__gte=last_24h)),
        escalated_24h=Count('id', filter=Q(created_at__gte=last_24h, message__contains='레벨 상향')),
    )
    active_sensor_row = (
        ai_qs.filter(created_at__gte=last_24h)
        .exclude(device_id='')
        .values('device_id')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')
        .first()
    )

    # 유형별 현황 (최근 7일)
    type_agg = {
        row['alarm_type']: row
        for row in ai_qs.filter(alarm_type__in=_AI_ALARM_LABELS)
        .values('alarm_type')
        .annotate(
            count_7d=Count('id', filter=Q(created_at__gte=last_7d)),
            count_24h=Count('id', filter=Q(created_at__gte=last_24h)),
            last_created=Max('created_at'),
        )
    }
    type_stats = sorted(
        [
            {
                'type':         atype,
                'label':        label,
                'count_7d':     type_agg.get(atype, {}).get('count_7d', 0),
                'count_24h':    type_agg.get(atype, {}).get('count_24h', 0),
                'last_created': type_agg.get(atype, {}).get('last_created'),
            }
            for atype, label in _AI_ALARM_LABELS.items()
        ],
        key=lambda x: x['count_7d'],
        reverse=True,
    )

    # 센서별 TOP 10 (최근 7일)
    top_sensors = list(
        ai_qs.filter(created_at__gte=last_7d)
        .exclude(device_id='')
        .values('device_id', 'sensor_type')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')[:10]
    )

    # ML 모델 학습 상태
    model_status = []
    total_models = 0
    try:
        from ml_engine.isolation_forest import _models as _if_models
        from ml_engine.arima_forecaster import _cache  as _arima_cache
        from ml_engine.cusum_detector    import _state  as _cusum_state

        all_keys = sorted(
            set(_if_models.keys()) | set(_arima_cache.keys()) | set(_cusum_state.keys())
        )
        for key in all_keys:
            model_status.append({
                'key':           key,
                'if_trained':    key in _if_models,
                'arima_trained': key in _arima_cache,
                'cusum_ready':   (
                    key in _cusum_state
                    and _cusum_state[key].get('mu') is not None
                ),
            })
        total_models = len(_if_models)
    except Exception:
        pass

    recent_alarms = ai_qs.order_by('-created_at')[:20]

    return render(request, 'backoffice/ai_metrics.html', {
        'active_menu': 'ai_metrics',
        'stats': {
            'total_24h':     summary['total_24h'],
            'total_all':     summary['total_all'],
            'active_sensor': active_sensor_row['device_id'] if active_sensor_row else '없음',
            'escalated_24h': summary['escalated_24h'],
            'total_models':  total_models,
        },
        'type_stats':      type_stats,
        'top_sensors':     top_sensors,
        'model_status':    model_status,
        'recent_alarms':   recent_alarms,
        'AI_ALARM_LABELS': _AI_ALARM_LABELS,
    })


@super_admin_required(menu_code='ai_metrics')
def eval_metrics_api(request):
    """AI 성능 평가 지표 JSON API — GET /backoffice/api/eval-metrics/?days=N"""
    from django.http import JsonResponse
    try:
        days = max(1, min(30, int(request.GET.get('days', '7'))))
    except (ValueError, TypeError):
        days = 7
    try:
        from ml_engine.evaluator import compute_proxy_metrics
        data = compute_proxy_metrics(days=days)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)
    return JsonResponse(data)
