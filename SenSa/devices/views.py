"""
devices 앱 뷰

- DeviceViewSet: 센서 장비 CRUD
- SensorDataView: 센서 측정 데이터 조회/생성
"""
import random

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Device, SensorData
from .serializers import DeviceSerializer


class DeviceViewSet(viewsets.ModelViewSet):
    """센서 장비 CRUD API"""
    queryset = Device.objects.filter(is_active=True)
    serializer_class = DeviceSerializer


class SensorDataView(APIView):
    """
    센서 데이터 히스토리 API

    GET  ?device_id=sensor_01&limit=20
    POST {"device_id": "sensor_01", "co": 12.3, ...}
    """

    def get(self, request):
        device_id = request.query_params.get('device_id')
        limit = int(request.query_params.get('limit', 20))

        try:
            device = Device.objects.get(device_id=device_id)
            data = SensorData.objects.filter(device=device)[:limit]
            result = [{
                'timestamp': d.timestamp.strftime('%H:%M:%S'),
                'co': d.co,
                'h2s': d.h2s,
                'co2': d.co2,
                'status': d.status,
            } for d in reversed(list(data))]
            return Response({'device_id': device_id, 'data': result})
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=404)

    def post(self, request):
        device_id = request.data.get('device_id')
        try:
            device = Device.objects.get(device_id=device_id)

            co = float(request.data.get('co', round(random.uniform(0, 100), 1)))
            h2s = float(request.data.get('h2s', round(random.uniform(0, 50), 1)))
            co2 = float(request.data.get('co2', round(random.uniform(300, 1000), 1)))

            # 상태 판별
            if co > 70 or h2s > 35 or co2 > 800:
                s = 'danger'
            elif co > 35 or h2s > 15 or co2 > 600:
                s = 'caution'
            else:
                s = 'normal'

            sd = SensorData.objects.create(
                device=device, co=co, h2s=h2s, co2=co2, status=s,
            )
            device.status = s
            device.last_value = co
            device.save()
            return Response({'id': sd.id, 'status': s}, status=201)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=404)
