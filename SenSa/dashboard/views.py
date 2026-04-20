"""
monitor 앱 뷰

- map_view: 관제 지도 페이지 (Template)
- MapImageViewSet: 공장 평면도 이미지 CRUD
- CheckGeofenceView: 지오펜스 내부 판별 + 알람 생성 (타 앱 연동 오케스트레이터)
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from geofence.models import GeoFence
from alerts.services import (
    check_worker_in_geofences,
    create_sensor_alarm,
    create_combined_alarm,
)
from .models import MapImage
from .serializers import MapImageSerializer


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
    """
    공장 평면도 이미지 CRUD

    POST /monitor/api/map/         : 새 지도 업로드
    GET  /monitor/api/map/current/ : 현재 활성 지도 조회
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    queryset = MapImage.objects.all()
    serializer_class = MapImageSerializer

    def perform_create(self, serializer):
        MapImage.objects.filter(is_active=True).update(is_active=False)
        serializer.save(is_active=True)

    @action(detail=False, methods=['get'])
    def current(self, request):
        """현재 활성 지도 조회"""
        current_map = MapImage.objects.filter(is_active=True).first()
        if current_map:
            serializer = self.get_serializer(current_map)
            return Response(serializer.data)
        return Response(
            {'detail': '업로드된 지도가 없습니다.'},
            status=status.HTTP_404_NOT_FOUND
        )


class CheckGeofenceView(APIView):
    """
    지오펜스 내부 판별 + 센서 이상 + 복합 위험 알람 생성

    POST /monitor/api/check-geofence/
    요청 body:
    {
      "workers": [
        {"worker_id": "worker_01", "name": "작업자 A", "x": 150, "y": 170}
      ],
      "sensors": [
        {"device_id": "sensor_01", "sensor_type": "gas", "status": "danger", "detail": "CO 250ppm"}
      ]
    }
    """

    def post(self, request):
        workers = request.data.get('workers', [])
        sensors = request.data.get('sensors', [])
        all_alarms = []

        # 1. 각 작업자 위치를 모든 지오펜스와 대조
        workers_in_fences = []

        for worker in workers:
            w_id = worker.get('worker_id', '')
            w_name = worker.get('name', w_id)
            w_x = float(worker.get('x', 0))
            w_y = float(worker.get('y', 0))

            fence_results = check_worker_in_geofences(w_id, w_name, w_x, w_y)

            for fr in fence_results:
                all_alarms.append({
                    **fr,
                    "worker_id": w_id,
                    "worker_name": w_name,
                })
                workers_in_fences.append({
                    "worker_id": w_id,
                    "geofence_id": fr["geofence_id"],
                    "geofence_name": fr["geofence_name"],
                    "zone_type": fr["zone_type"],
                })

        # 2. 센서 상태 알람 처리
        for sensor in sensors:
            s_id = sensor.get('device_id', '')
            s_type = sensor.get('sensor_type', '')
            s_status = sensor.get('status', 'normal')
            s_detail = sensor.get('detail', '')

            alarm = create_sensor_alarm(s_id, s_type, s_status, s_detail)
            if alarm:
                all_alarms.append(alarm)

        # 3. 복합 위험 판별
        danger_sensors = [s for s in sensors if s.get('status') in ('danger', 'caution')]

        if workers_in_fences and danger_sensors:
            for wf in workers_in_fences:
                for ds in danger_sensors:
                    try:
                        fence_obj = GeoFence.objects.get(id=wf['geofence_id'])
                        combined = create_combined_alarm(
                            worker_id=wf['worker_id'],
                            worker_name=wf.get('worker_name', wf['worker_id']),
                            geofence=fence_obj,
                            device_id=ds.get('device_id', ''),
                            sensor_status=ds.get('status', ''),
                        )
                        all_alarms.append(combined)
                    except GeoFence.DoesNotExist:
                        pass

        return Response({
            "alarms": all_alarms,
            "workers_in_fences": workers_in_fences,
            "alarm_count": len(all_alarms),
        })
