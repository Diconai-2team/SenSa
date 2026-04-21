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
from realtime.publishers import publish_sensor_update


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

            co  = float(request.data.get('co',  round(random.uniform(0, 100), 1)))
            h2s = float(request.data.get('h2s', round(random.uniform(0, 50),  1)))
            co2 = float(request.data.get('co2', round(random.uniform(300, 1000), 1)))
            o2  = request.data.get('o2')
            o2  = float(o2) if o2 is not None else None

            # 상태 판별 — MD 스펙 임계치 기준
            # O2: 구간형 (19.5~23.5 정상 / 18~19.5 또는 23.5~25 주의 / <18 또는 >25 위험)
            def classify_o2(val):
                if val is None: return 'normal'
                if val < 18 or val > 25: return 'danger'
                if val < 19.5 or val > 23.5: return 'caution'
                return 'normal'

            gas_status = [
                'danger'  if co  >= 200  else 'caution' if co  >= 25   else 'normal',
                'danger'  if h2s >= 50   else 'caution' if h2s >= 10   else 'normal',
                'danger'  if co2 >= 5000 else 'caution' if co2 >= 1000 else 'normal',
                classify_o2(o2),
            ]
            if 'danger' in gas_status:
                s = 'danger'
            elif 'caution' in gas_status:
                s = 'caution'
            else:
                s = 'normal'

            sd = SensorData.objects.create(
                device=device, co=co, h2s=h2s, co2=co2, o2=o2, status=s,
            )
            device.status = s
            device.last_value = co
            device.save()
            
            # ═══════════════════════════════════════════════
            # WS push — Phase D 추가
            # ═══════════════════════════════════════════════
            publish_sensor_update({
                "device_id": device.device_id,
                "sensor_type": device.sensor_type,
                "status": s,
                "values": {
                    "co": co,
                    "h2s": h2s,
                    "co2": co2,
                    "o2": o2,
                },
                "timestamp": sd.timestamp.isoformat(),
            })
            
            return Response({'id': sd.id, 'status': s}, status=201)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=404)
