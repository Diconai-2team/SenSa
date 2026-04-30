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
from .serializers import MapImageSerializer
from realtime.publishers import publish_alarm
import math


# ============================================================
# 페이지 뷰
# ============================================================


@login_required(login_url="/accounts/login/")
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
            user=request.user,
            check_date=today,
        ).exists()
    except Exception:
        checklist_done = False

    try:
        from vr_training.models import VRTrainingLog

        vr_done = VRTrainingLog.objects.filter(
            user=request.user,
            check_date=today,
            is_completed=True,
        ).exists()
    except Exception:
        vr_done = False

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "safety_checklist_done_today": checklist_done,
            "vr_training_done_today": vr_done,
        },
    )


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

    @action(detail=False, methods=["get"])
    def current(self, request):
        current_map = MapImage.objects.filter(is_active=True).first()
        if current_map:
            serializer = self.get_serializer(current_map)
            return Response(serializer.data)
        return Response(
            {"detail": "업로드된 지도가 없습니다."}, status=status.HTTP_404_NOT_FOUND
        )


PROXIMITY_RADIUS = 200  # 픽셀. 작업자가 센서에서 이 반경 안에 있으면 영향받음


def _compute_nearby_sensor_status(
    worker_x: float, worker_y: float, sensors: list, radius: float = PROXIMITY_RADIUS
) -> tuple[str, list]:
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
    worst = "normal"
    influencing: list = []

    for s in sensors:
        sensor_status = s.get("status", "normal")

        # ── B1: normal 센서는 거리 계산 생략 ──
        if sensor_status == "normal":
            continue

        sx = float(s.get("x", 0))
        sy = float(s.get("y", 0))
        distance = math.sqrt((sx - worker_x) ** 2 + (sy - worker_y) ** 2)
        if distance > radius:
            continue

        # ── B3: 영향 센서 기록 ──
        device_id = s.get("device_id", "")
        influencing.append((device_id, sensor_status))

        if sensor_status == "danger":
            worst = "danger"
        elif worst != "danger":  # caution, 아직 danger 아닐 때만 승격
            worst = "caution"

    return worst, influencing


@method_decorator(csrf_exempt, name="dispatch")
class CheckGeofenceView(APIView):
    """작업자/센서 상태 전이 기반 알람 오케스트레이터"""

    def post(self, request):
        workers = request.data.get("workers", [])
        sensors = request.data.get("sensors", [])

        all_alarms = []

        # 1) 작업자 축 판정 — 각 작업자별로 근접 센서만 평가
        for worker in workers:
            w_id = worker.get("worker_id", "")
            if not w_id:
                continue

            w_x = float(worker.get("x", 0))
            w_y = float(worker.get("y", 0))

            # B1 + B3 : worst_status 와 함께 영향 센서 목록도 받음
            nearby_status, influencing_sensors = _compute_nearby_sensor_status(
                w_x, w_y, sensors
            )

            alarms = evaluate_worker(
                worker_id=w_id,
                worker_name=worker.get("name", w_id),
                x=w_x,
                y=w_y,
                worst_sensor_status=nearby_status,
                influencing_sensors=influencing_sensors,  # B3
            )
            all_alarms.extend(alarms)

        # 2) 센서 축 판정 — 기존 그대로
        for sensor in sensors:
            d_id = sensor.get("device_id", "")
            if not d_id:
                continue
            alarms = evaluate_sensor(
                device_id=d_id,
                sensor_type=sensor.get("sensor_type", ""),
                observed_status=sensor.get("status", "normal"),
                detail=sensor.get("detail", ""),
            )
            all_alarms.extend(alarms)

        # 3) WS 방송
        for alarm in all_alarms:
            publish_alarm(alarm)

        return Response(
            {
                "alarms": all_alarms,
                "alarm_count": len(all_alarms),
            }
        )
