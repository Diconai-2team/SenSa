"""
monitor 앱 뷰

- map_view: 관제 지도 페이지 (Template)
- MapImageViewSet: 공장 평면도 이미지 CRUD
- CheckGeofenceView: 상태 전이 기반 알람 오케스트레이터

[변경 이력]
  Phase E7 : 브라우저 시뮬 제거 후 안정화
  v2       : map_view 에 safety_checklist_done_today / vr_training_done_today context
  v3 (팀원 병합):
    - B1 : 근접 센서 계산 시 normal 센서는 거리 계산 스킵 (O(N·M) → O(N·k))
           수학적으론 동어반복이지만 의미 명확화 + 미미한 성능 개선
    - B3 : 영향 센서 목록 수집 (어떤 센서가 알람 원인인지 로깅용)
           evaluate_worker 로 전달되어 알람 메시지에 반영됨
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from alerts.services import evaluate_worker, evaluate_sensor
from .models import MapImage


# ════════════════════════════════════════════════════════════
# [Phase 4 P4-B] 커스텀 Prometheus 메트릭 — AI forecast
# ════════════════════════════════════════════════════════════
# 4단계 문서 STEP 4: "지오펜스 판단 시간, AI 분석 시간, 알람 발생 횟수 등
# 핵심 구간의 custom counter / histogram을 추가한다"
#
# 메트릭이 노출되는 곳: GET /metrics (django-prometheus 가 자동 통합)
# 활용 예시 (Prometheus query):
#   - p95 ARIMA 시간:
#       histogram_quantile(0.95, rate(sensa_ai_forecast_duration_seconds_bucket{algorithm="arima(1,1,0)"}[5m]))
#   - algorithm 별 호출 비율:
#       rate(sensa_ai_forecast_total[1m])
from prometheus_client import Histogram, Counter

ai_forecast_duration = Histogram(
    'sensa_ai_forecast_duration_seconds',
    'AI forecast (ARIMA 또는 linear) 실행 시간',
    labelnames=('algorithm',),
    # bucket: 1ms ~ 2.5s — ARIMA fit 평균 50ms 기준 정밀
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
ai_forecast_total = Counter(
    'sensa_ai_forecast_total',
    'AI forecast 호출 수 (algorithm 별)',
    labelnames=('algorithm',),
)
from .serializers import MapImageSerializer
from realtime.publishers import publish_alarm
import math


# ============================================================
# 페이지 뷰
# ============================================================

@login_required(login_url='/accounts/login/')
def map_view(request):
    """
    관제 지도 페이지.

    context:
        safety_checklist_done_today (bool)
        vr_training_done_today (bool)
    """
    today = timezone.localdate()

    try:
        from safety.models import SafetyChecklist
        checklist_done = SafetyChecklist.objects.filter(
            user=request.user, check_date=today,
        ).exists()
    except Exception:
        checklist_done = False

    try:
        from vr_training.models import VRTrainingLog
        vr_done = VRTrainingLog.objects.filter(
            user=request.user, check_date=today, is_completed=True,
        ).exists()
    except Exception:
        vr_done = False

    return render(request, 'dashboard/dashboard.html', {
        'safety_checklist_done_today': checklist_done,
        'vr_training_done_today':      vr_done,
    })


# ============================================================
# API 뷰
# ============================================================

class MapImageViewSet(viewsets.ModelViewSet):
    """공장 평면도 이미지 CRUD"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    queryset = MapImage.objects.all()
    serializer_class = MapImageSerializer

    def perform_create(self, serializer):
        MapImage.objects.filter(is_active=True).update(is_active=False)
        serializer.save(is_active=True)

    @action(detail=False, methods=['get'])
    def current(self, request):
        current_map = MapImage.objects.filter(is_active=True).first()
        if current_map:
            serializer = self.get_serializer(current_map)
            return Response(serializer.data)
        return Response(
            {'detail': '업로드된 지도가 없습니다.'},
            status=status.HTTP_404_NOT_FOUND
        )


PROXIMITY_RADIUS = 200   # 픽셀. 작업자가 센서에서 이 반경 안에 있으면 영향받음


def _compute_nearby_sensor_status(worker_x: float, worker_y: float,
                                   sensors: list,
                                   radius: float = PROXIMITY_RADIUS) -> tuple[str, list]:
    """
    작업자 좌표 기준 반경 내 센서들의 최악 상태 반환.

    [팀원 병합 v3]
      B1: normal 센서는 거리 계산 자체를 스킵 (early continue)
          → 대부분의 시간 동안 센서 대부분이 normal 상태라
            실제 sqrt 호출 횟수가 크게 줄어듦.
            수학적 의미는 동일하지만 코드 의도가 명확해짐.

      B3: 반환값에 영향 센서 목록도 함께 돌려줌.
          형식: [(device_id, status), ...]
          알람 메시지에 "어떤 센서 때문인지" 로깅하는 용도.

    Returns:
        (worst_status, influencing_sensors)
          - worst_status: 'normal' | 'caution' | 'danger'
          - influencing_sensors: [(device_id, status), ...] 반경 내 비정상 센서만
    """
    worst = 'normal'
    influencing: list = []

    for s in sensors:
        sensor_status = s.get('status', 'normal')

        # ── B1: normal 센서는 거리 계산 생략 ──
        if sensor_status == 'normal':
            continue

        sx = float(s.get('x', 0))
        sy = float(s.get('y', 0))
        distance = math.sqrt((sx - worker_x) ** 2 + (sy - worker_y) ** 2)
        if distance > radius:
            continue

        # ── B3: 영향 센서 기록 ──
        device_id = s.get('device_id', '')
        influencing.append((device_id, sensor_status))

        if sensor_status == 'danger':
            worst = 'danger'
        elif worst != 'danger':  # caution, 아직 danger 아닐 때만 승격
            worst = 'caution'

    return worst, influencing


@method_decorator(csrf_exempt, name='dispatch')
class CheckGeofenceView(APIView):
    """작업자/센서 상태 전이 기반 알람 오케스트레이터"""

    def post(self, request):
        workers = request.data.get('workers', [])
        sensors = request.data.get('sensors', [])

        all_alarms = []

        # 1) 작업자 축 판정 — 각 작업자별로 근접 센서만 평가
        for worker in workers:
            w_id = worker.get('worker_id', '')
            if not w_id:
                continue

            w_x = float(worker.get('x', 0))
            w_y = float(worker.get('y', 0))

            # B1 + B3 : worst_status 와 함께 영향 센서 목록도 받음
            nearby_status, influencing_sensors = _compute_nearby_sensor_status(
                w_x, w_y, sensors
            )

            alarms = evaluate_worker(
                worker_id=w_id,
                worker_name=worker.get('name', w_id),
                x=w_x,
                y=w_y,
                worst_sensor_status=nearby_status,
                influencing_sensors=influencing_sensors,   # B3
            )
            all_alarms.extend(alarms)

        # 2) 센서 축 판정 — 기존 그대로
        for sensor in sensors:
            d_id = sensor.get('device_id', '')
            if not d_id:
                continue
            alarms = evaluate_sensor(
                device_id=d_id,
                sensor_type=sensor.get('sensor_type', ''),
                observed_status=sensor.get('status', 'normal'),
                detail=sensor.get('detail', ''),
            )
            all_alarms.extend(alarms)

        # 3) WS 방송
        for alarm in all_alarms:
            publish_alarm(alarm)

        return Response({
            'alarms': all_alarms,
            'alarm_count': len(all_alarms),
        })

# ============================================================
# G1 — AI Forecast View
# ============================================================
# 4차 프로젝트 1단계 (AI 이상탐지) 문서의 UI 연동 요구:
#   - 실제값 / 예측값 / 오차 / 경고 구간 같이 시각화
#   - 운영자 친화 메시지: "X분 내 위험 가능성", "평상시 대비 급증"
# 1차 — slope 외삽 + z-score anomaly. ARIMA 보강은 발표 후.

class AIForecastView(APIView):
    """다음 N틱 예측 + 운영자 메시지.

    GET /dashboard/api/ai-forecast/?device_id=sensor_04&metric=co&horizon=60
    """
    permission_classes = [IsAuthenticated]

    # 가스 + 전력 임계 (caution / danger / unit)
    THRESHOLDS = {
        'co':      {'w': 25,    'd': 200,  'unit': 'ppm'},
        'h2s':     {'w': 10,    'd': 50,   'unit': 'ppm'},
        'co2':     {'w': 1000,  'd': 5000, 'unit': 'ppm'},
        'no2':     {'w': 3,     'd': 5,    'unit': 'ppm'},
        'so2':     {'w': 2,     'd': 5,    'unit': 'ppm'},
        'o3':      {'w': 0.05,  'd': 0.1,  'unit': 'ppm'},
        'nh3':     {'w': 25,    'd': 50,   'unit': 'ppm'},
        'voc':     {'w': 0.5,   'd': 2.0,  'unit': 'ppm'},
        'o2':      {'w': None,  'd': None, 'unit': '%'},  # 양방향, 별도 처리
        'current': {'w': 15,    'd': 25,   'unit': 'A'},
        'voltage': {'w': 240,   'd': 250,  'unit': 'V'},
        'watt':    {'w': 5000,  'd': 8000, 'unit': 'W'},
        'temp':    {'w': 80,    'd': 120,  'unit': '°C'},
    }

    def get(self, request):
        device_id = request.query_params.get('device_id')
        metric = request.query_params.get('metric')
        try:
            horizon = int(request.query_params.get('horizon', 60))
        except (ValueError, TypeError):
            horizon = 60
        horizon = max(10, min(horizon, 200))  # 클램프

        if not device_id or not metric:
            return Response({'error': 'device_id, metric 필수'}, status=400)
        if metric not in self.THRESHOLDS:
            return Response({'error': f'unknown metric {metric}'}, status=400)

        th = self.THRESHOLDS[metric]

        from devices.models import SensorData, Device
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': f'device {device_id} 없음'}, status=404)

        # 최근 30개 SensorData
        recent_qs = SensorData.objects.filter(device=device).order_by('-timestamp')[:30]
        recent_values = []
        for sd in recent_qs:
            v = getattr(sd, metric, None)
            if v is not None:
                recent_values.append(float(v))
        recent_values.reverse()  # 오래된 → 최근

        if len(recent_values) < 5:
            return Response({
                'device_id': device_id, 'metric': metric,
                'horizon_ticks': horizon,
                'current_value': recent_values[-1] if recent_values else None,
                'actual_recent': recent_values, 'predicted': [],
                'slope': 0.0,
                'risk_message': '데이터 부족',
                'predicted_threshold_ticks': None,
                'is_anomaly': False,
                'threshold_caution': th['w'], 'threshold_danger': th['d'],
                'unit': th['unit'],
            })

        current = recent_values[-1]
        slope = self._calc_slope(recent_values)

        # [ARIMA 보강] 1차: ARIMA(1,1,0), fallback: 선형 slope 외삽
        from alerts.services.arima_forecast import arima_forecast, ARIMA_AVAILABLE
        # [P4-B] AI forecast 실행 시간 측정 시작
        import time as _time
        _ai_start = _time.perf_counter()
        arima_predicted = arima_forecast(recent_values, horizon=horizon)
        if arima_predicted is not None:
            algorithm = 'arima(1,1,0)'
            predicted = [round(v, 3) for v in arima_predicted]
        else:
            # fallback — 선형 외삽 (ARIMA 미설치 또는 fit 실패)
            predicted = [round(current + slope * (i + 1), 3) for i in range(horizon)]
            algorithm = 'linear' if ARIMA_AVAILABLE else 'linear (statsmodels 미설치)'
        # [P4-B] 메트릭 기록 — algorithm 별 실행 시간 + 호출 수
        _ai_elapsed = _time.perf_counter() - _ai_start
        try:
            ai_forecast_duration.labels(algorithm=algorithm).observe(_ai_elapsed)
            ai_forecast_total.labels(algorithm=algorithm).inc()
        except Exception:
            pass   # 메트릭 실패가 API 영향 없게

        # 임계 도달 예상 시점 (ARIMA 시계열 우선, 없으면 slope)
        predicted_threshold_ticks = None
        if th['w'] is not None and current < th['w']:
            if algorithm.startswith('arima'):
                # ARIMA 의 forecast 시계열에서 첫 임계 초과 시점 찾기
                for i, pv in enumerate(predicted):
                    if pv >= th['w']:
                        predicted_threshold_ticks = i + 1
                        break
            elif slope > 0:
                ticks = (th['w'] - current) / slope
                if 0 < ticks <= horizon * 10:
                    predicted_threshold_ticks = int(ticks)

        # z-score anomaly (잔차 기반 — 1단계 문서 6.1 잔차 기반 이상 탐지)
        is_anomaly = False
        if len(recent_values) >= 10:
            import statistics
            window = recent_values[-10:-1]
            mean = statistics.mean(window)
            stdev = statistics.stdev(window) if len(window) > 1 else 0
            if stdev > 0:
                z_score = abs(current - mean) / stdev
                is_anomaly = z_score > 3.0

        risk_message = self._risk_message(
            current, slope, th, predicted_threshold_ticks, is_anomaly, metric,
        )

        return Response({
            'device_id': device_id, 'metric': metric,
            'horizon_ticks': horizon,
            'current_value': round(current, 3),
            'actual_recent': [round(v, 3) for v in recent_values],
            'predicted': predicted,
            'slope': round(slope, 5),
            'risk_message': risk_message,
            'predicted_threshold_ticks': predicted_threshold_ticks,
            'is_anomaly': is_anomaly,
            'threshold_caution': th['w'],
            'threshold_danger': th['d'],
            'unit': th['unit'],
            'algorithm': algorithm,   # [ARIMA 보강] 'arima(1,1,0)' 또는 'linear...'
        })

    def _calc_slope(self, values):
        n = len(values)
        if n < 2:
            return 0.0
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(values) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
        den = sum((x - mean_x) ** 2 for x in xs)
        return num / den if den > 1e-9 else 0.0

    def _risk_message(self, current, slope, th, predicted_ticks, is_anomaly, metric):
        """운영자 친화 메시지 — 1단계 문서 9. UI 연동 패턴."""
        # O2 양방향 (저산소/고산소)
        if metric == 'o2':
            if current < 18 or current > 21.5:
                return '산소 농도 이상'
            return '정상'

        if th['w'] is None:
            return '정상'

        # 이미 임계 초과
        if current >= th['d']:
            return '위험 — 즉시 조치'
        if current >= th['w']:
            return '주의 — 임계 진입'

        # 잔차 기반 anomaly
        if is_anomaly:
            return '평상시 대비 이상 급증'

        # 예측 임계 도달
        if predicted_ticks is not None:
            mins = predicted_ticks / 60  # 1틱 ≈ 1초 가정
            if mins < 5:
                return f'약 {int(mins) + 1}분 내 위험 가능성'
            elif mins < 60:
                return f'약 {int(mins)}분 내 위험 도달 예상'
            else:
                return f'{round(mins / 60, 1)}시간 내 위험 가능성'

        # 추세 (slope)
        if slope > 0.1:
            return '상승 추세 — 모니터링'

        return '정상'


# ============================================================
# P2 STEP 7 — Celery Task Status View
# ============================================================
# 2단계 문서 STEP 7. 작업 상태 추적 구조:
#   "task 실행 결과를 DB 또는 상태 조회 API로 확인할 수 있게 한다."
# Celery 의 AsyncResult 활용 — CELERY_RESULT_BACKEND=redis 가 설정돼야 작동.

class TaskStatusView(APIView):
    """Celery task 상태 조회.

    GET /dashboard/api/task-status/<task_id>/

    Response:
        {
          "task_id": "xxx-yyy-zzz",
          "status": "PENDING" | "STARTED" | "SUCCESS" | "FAILURE" | "RETRY",
          "ready": bool,
          "successful": bool | null,
          "result": {...} | str | null,
          "date_done": "2026-05-20T07:30:00" | null,
          "traceback": str | null
        }

    상태 의미:
      PENDING : 아직 worker 가 받지 않음 (큐에 대기 중)
      STARTED : worker 가 실행 시작
      SUCCESS : 정상 완료
      FAILURE : 예외로 실패
      RETRY   : 재시도 중
      REVOKED : 취소됨
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        from celery.result import AsyncResult

        result = AsyncResult(task_id)

        # successful() / failed() 는 ready 일 때만 의미 있음
        ready = result.ready()
        successful = result.successful() if ready else None

        # result.result 가 예외이면 직렬화 안 됨 → 문자열로
        task_result = None
        traceback = None
        if successful:
            task_result = result.result
        elif ready and not successful:
            task_result = str(result.result) if result.result else None
            traceback = result.traceback

        date_done = None
        if result.date_done:
            date_done = result.date_done.isoformat()

        return Response({
            'task_id': task_id,
            'status': result.status,
            'ready': ready,
            'successful': successful,
            'result': task_result,
            'date_done': date_done,
            'traceback': traceback,
        })
