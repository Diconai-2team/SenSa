"""
devices/views.py — 센서 장비 CRUD + 센서 데이터 수신/저장

[변경 이력]
  Phase D : 4종 가스 저장 + publish_sensor_update
  Gas 병합: 9종 가스 확장 + 통일 임계치
  Power 병합:
    - POST /sensor-data/ 가 gas / power 양쪽 수용
    - power 타입이면 current/voltage/watt 저장 + alerts.services.classify_power 위임
    - 동적 전력 판정(24h 중앙값)이 실제로 돌려면 이 저장 경로가 필수
  Step 1A (가스 패널 페이지네이션화):
    - DeviceViewSet 에 sensor_type 쿼리 필터 추가
      → /dashboard/api/device/?sensor_type=gas 로 가스 센서만 받아갈 수 있음
      → 대시보드 가스/전력 패널이 자기 종류 센서 목록만 페이지네이션 구성용으로 사용

[설계 원칙]
  - status 판정은 이 뷰가 단일 출처 → alerts.services 의 classify_* 재사용
  - 판정 로직을 이 파일에서 복제하지 않고 alerts.services 를 신뢰
  - publish_sensor_update 시그니처 불변
"""
from rest_framework import viewsets, status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Device, SensorData
from .serializers import DeviceSerializer
from realtime.publishers import publish_sensor_update
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

# 판정 로직은 alerts.services 에 단일 정의 — 여기서는 호출만
from alerts.services import classify_gas, classify_power


# ═══════════════════════════════════════════════════════════
# Device CRUD
# ═══════════════════════════════════════════════════════════

class DeviceViewSet(viewsets.ModelViewSet):
    """
    센서 장비 CRUD API.

    [필터]
      ?sensor_type=gas|power|temperature|motion
        한 종류의 센서 목록만 받아갈 때 사용.
        대시보드 가스/전력 패널이 페이지네이션 구성용으로 호출.
    """
    queryset = Device.objects.filter(is_active=True)
    serializer_class = DeviceSerializer

    def get_queryset(self):
        """sensor_type 쿼리 파라미터로 필터링 지원 (Step 1A)."""
        qs = super().get_queryset()
        sensor_type = self.request.query_params.get('sensor_type')
        if sensor_type:
            qs = qs.filter(sensor_type=sensor_type)
        return qs


# ═══════════════════════════════════════════════════════════
# 센서 측정값 조회/생성 — gas / power 양쪽 수용
# ═══════════════════════════════════════════════════════════

@method_decorator(csrf_exempt, name='dispatch')
class SensorDataView(APIView):
    """
    센서 데이터 히스토리 API

    GET  ?device_id=sensor_01&limit=20

    POST (gas):
      {"device_id": "sensor_01", "sensor_type": "gas",
       "co": 12.3, "h2s": 2.1, ..., "voc": 0.15}

    POST (power):
      {"device_id": "power_01", "sensor_type": "power",
       "current": 12.3, "voltage": 220.1, "watt": 2712.5}

    응답(POST): {"id": <sd_id>, "status": "normal"|"caution"|"danger"}

    sensor_type 누락 시 기존 호환을 위해 gas 로 간주.
    """

    # ─── 조회 ───
    def get(self, request):
        device_id = request.query_params.get('device_id')
        limit = int(request.query_params.get('limit', 20))

        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=http_status.HTTP_404_NOT_FOUND)

        data = SensorData.objects.filter(device=device)[:limit]

        result = [{
            'timestamp': d.timestamp.strftime('%H:%M:%S'),
            # 가스 9종
            'co': d.co, 'h2s': d.h2s, 'co2': d.co2, 'o2': d.o2,
            'no2': d.no2, 'so2': d.so2, 'o3': d.o3, 'nh3': d.nh3, 'voc': d.voc,
            # 전력 3종 (Power 병합)
            'current': d.current, 'voltage': d.voltage, 'watt': d.watt,
            'status': d.status,
        } for d in reversed(list(data))]
        return Response({'device_id': device_id, 'data': result})

    # ─── 생성 ───
    def post(self, request):
        device_id = request.data.get('device_id')
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=http_status.HTTP_404_NOT_FOUND)

        # sensor_type 추출 — 명시되지 않으면 Device.sensor_type 으로 fallback
        sensor_type = request.data.get('sensor_type') or device.sensor_type

        def _get_float(key):
            v = request.data.get(key)
            return float(v) if v is not None else None

        # ═══════════════════════════════════════════════════
        # 분기: gas / power 별로 파싱 + 판정 + 저장
        # ═══════════════════════════════════════════════════
        if sensor_type == 'gas':
            sd, s, payload_values = self._save_gas(device, _get_float)
        elif sensor_type == 'power':
            sd, s, payload_values = self._save_power(device, _get_float)
        else:
            return Response(
                {'error': f'미지원 sensor_type: {sensor_type}'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # ═══════════════════════════════════════════════════
        # 공통: Device 상태 갱신 + WS push
        # ═══════════════════════════════════════════════════
        device.status = s
        device.save(update_fields=['status', 'last_value'])

        publish_sensor_update({
            "device_id":   device.device_id,
            "sensor_type": sensor_type,
            "status":      s,
            "values":      payload_values,
            "timestamp":   sd.timestamp.isoformat(),
        })

        return Response(
            {'id': sd.id, 'status': s},
            status=http_status.HTTP_201_CREATED,
        )

    # ─── 가스 저장 ───
    def _save_gas(self, device, _get_float):
        gas = {
            'co':  _get_float('co'),
            'h2s': _get_float('h2s'),
            'co2': _get_float('co2'),
            'o2':  _get_float('o2'),
            'no2': _get_float('no2'),
            'so2': _get_float('so2'),
            'o3':  _get_float('o3'),
            'nh3': _get_float('nh3'),
            'voc': _get_float('voc'),
        }
        # 판정 — alerts.services 단일 출처
        s = classify_gas(gas)

        sd = SensorData.objects.create(
            device=device,
            co=gas['co'],   h2s=gas['h2s'], co2=gas['co2'], o2=gas['o2'],
            no2=gas['no2'], so2=gas['so2'], o3=gas['o3'],
            nh3=gas['nh3'], voc=gas['voc'],
            status=s,
        )
        # 지도 마커용 대표값: CO
        if gas['co'] is not None:
            device.last_value = gas['co']
        return sd, s, gas

    # ─── 전력 저장 ───
    def _save_power(self, device, _get_float):
        power = {
            'current': _get_float('current'),
            'voltage': _get_float('voltage'),
            'watt':    _get_float('watt'),
        }
        # 판정 — 동적 24h 중앙값 기반 (device_id 전달 필수)
        s = classify_power(power, device.device_id)

        sd = SensorData.objects.create(
            device=device,
            current=power['current'],
            voltage=power['voltage'],
            watt=power['watt'],
            status=s,
        )
        # 지도 마커용 대표값: watt
        if power['watt'] is not None:
            device.last_value = power['watt']
        return sd, s, power