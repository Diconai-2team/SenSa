"""
monitor 앱 뷰

- map_view: 관제 지도 페이지 (Template)
- MapImageViewSet: 공장 평면도 이미지 CRUD
- CheckGeofenceView: 상태 전이 기반 알람 오케스트레이터
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from alerts.services import evaluate_worker, evaluate_sensor, check_geofence_transitions
from .models import MapImage
from .serializers import MapImageSerializer
from realtime.publishers import publish_alarm
import math

# ============================================================
# 페이지 뷰
# ============================================================

@login_required(login_url='/accounts/login/')
def map_view(request):
    """관제 지도 페이지"""
    return render(request, 'dashboard/dashboard.html')


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


SENSOR_RADIUS = 200   # px — 센서 감지 반경 (센서 기준)


def _get_sensor_influence(worker_x: float, worker_y: float,
                           sensors: list, radius: float = SENSOR_RADIUS):
    """
    센서 반경 내에 작업자가 있는지 확인 (센서 기준 탐지).
    normal 센서는 스킵 — 위험한 센서만 거리 계산.
    
    반환: (worst_status, influencing_sensors)
      - worst_status: 'normal' | 'caution' | 'danger'
      - influencing_sensors: [(device_id, status), ...] 반경 내 비정상 센서 목록
    """
    worst = 'normal'
    influencing = []
    
    for s in sensors:
        sensor_status = s.get('status', 'normal')
        if sensor_status == 'normal':
            continue
        sx = float(s.get('x', 0))
        sy = float(s.get('y', 0))
        if math.sqrt((sx - worker_x) ** 2 + (sy - worker_y) ** 2) <= radius:
            influencing.append((s.get('device_id', ''), sensor_status))
            if sensor_status == 'danger':
                worst = 'danger'
            elif worst != 'danger':
                worst = 'caution'
    
    return worst, influencing


@method_decorator(csrf_exempt, name='dispatch')
class CheckGeofenceView(APIView):
    """작업자/센서 상태 전이 기반 알람 오케스트레이터"""

    def post(self, request):
        workers = request.data.get('workers', [])
        sensors = request.data.get('sensors', [])
        
        # 1) 작업자 축 판정 — 각 작업자별로 근접 센서만 평가
        all_alarms = []
        for worker in workers:
            w_id = worker.get('worker_id', '')
            if not w_id:
                continue
            
            w_x = float(worker.get('x', 0))
            w_y = float(worker.get('y', 0))
            
            # 이 작업자 위치에 영향을 주는 센서 상태 (센서 기준 탐지)
            sensor_influence, influencing_sensors = _get_sensor_influence(w_x, w_y, sensors)

            # 센서 기반 상태 전이 알람
            alarms = evaluate_worker(
                worker_id=w_id,
                worker_name=worker.get('name', w_id),
                x=w_x,
                y=w_y,
                worst_sensor_status=sensor_influence,
                influencing_sensors=influencing_sensors,
            )
            all_alarms.extend(alarms)

            # 지오펜스 진입/이탈 알람 (별개)
            fence_alarms = check_geofence_transitions(
                worker_id=w_id,
                worker_name=worker.get('name', w_id),
                x=w_x,
                y=w_y,
            )
            all_alarms.extend(fence_alarms)
        
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
