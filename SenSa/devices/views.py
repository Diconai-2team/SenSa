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
# viewsets — ModelViewSet 사용 / status — HTTP 상태 코드 상수 (이름 충돌 회피 위해 http_status로 alias)
# 이유: STATUS_CHOICES('status' 변수)와 충돌 방지
from rest_framework.response import Response
# DRF용 JSON 응답 클래스
from rest_framework.views import APIView
# DRF 클래스 기반 뷰의 기본 부모 — SensorDataView가 상속

from .models import Device, SensorData
from .serializers import DeviceSerializer
from realtime.publishers import publish_sensor_update
# WebSocket 푸시 헬퍼 — 측정값 수신 즉시 대시보드 클라이언트에 broadcast
# Channels 기반으로 추정 (alerts.state_store가 같은 Redis 사용)
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
# CSRF 면제 — 외부 센서 디바이스가 토큰 없이 POST 가능하게 하기 위함

# 판정 로직은 alerts.services 에 단일 정의 — 여기서는 호출만
from alerts.services import classify_gas, classify_power
# 단일 출처 원칙 — 가스/전력 임계치 판정 로직 중복 정의 금지
# 이 파일은 "수신/저장/푸시"만 담당하고 판정은 alerts에 위임


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
    # ModelViewSet — list/retrieve/create/update/destroy 모두 자동 제공
    # alerts의 ReadOnlyModelViewSet과 다름: 알람은 자동 생성만, 장비는 운영자가 CRUD 가능
    queryset = Device.objects.filter(is_active=True)
    # 활성 센서만 노출 — 논리 삭제(is_active=False)된 센서는 API에서 안 보임
    serializer_class = DeviceSerializer

    def get_queryset(self):
        """sensor_type 쿼리 파라미터로 필터링 지원 (Step 1A)."""
        # 동적 필터링 — query string에 따라 쿼리셋 좁히기
        qs = super().get_queryset()
        # 부모의 기본 queryset(is_active=True)부터 시작
        sensor_type = self.request.query_params.get('sensor_type')
        # ?sensor_type=gas 같은 query string 추출 — 없으면 None
        if sensor_type:
            qs = qs.filter(sensor_type=sensor_type)
            # 가스 패널은 ?sensor_type=gas, 전력 패널은 ?sensor_type=power로 호출
        return qs


# ═══════════════════════════════════════════════════════════
# 센서 측정값 조회/생성 — gas / power 양쪽 수용
# ═══════════════════════════════════════════════════════════

@method_decorator(csrf_exempt, name='dispatch')
# 클래스의 dispatch 메서드에 csrf_exempt 적용 — 모든 HTTP 메서드에서 CSRF 면제
# 외부 센서 디바이스(IoT)는 CSRF 토큰을 못 가지므로 면제 필수
# ⚠️ 보안 위험: 운영 환경에선 IP 화이트리스트나 API 키 인증 추가 권장
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
        # 특정 센서의 최근 N건 측정 히스토리 반환 — 대시보드 차트 데이터 소스
        device_id = request.query_params.get('device_id')
        limit = int(request.query_params.get('limit', 20))
        # 기본 20건 — 차트 X축 길이와 일치하는 UX 최적값
        # ⚠️ int() 변환 — 'abc' 같은 문자열 들어오면 ValueError 발생, 400으로 변환되지 않음

        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=http_status.HTTP_404_NOT_FOUND)
            # 존재하지 않는 device_id로 조회 시 404 + 한국어 메시지

        data = SensorData.objects.filter(device=device)[:limit]
        # Meta.ordering=['-timestamp']로 최신순 자동 정렬 → 슬라이싱으로 최근 N건

        result = [{
            'timestamp': d.timestamp.strftime('%H:%M:%S'),
            # 시각만 추출 (HH:MM:SS) — 차트 X축 라벨 용도, 날짜 정보는 손실
            # ⚠️ 자정 넘어가면 같은 라벨이 두 번 나타날 수 있음 (00:30이 어제인지 오늘인지 모름)
            # 가스 9종
            'co': d.co, 'h2s': d.h2s, 'co2': d.co2, 'o2': d.o2,
            'no2': d.no2, 'so2': d.so2, 'o3': d.o3, 'nh3': d.nh3, 'voc': d.voc,
            # 전력 3종 (Power 병합)
            'current': d.current, 'voltage': d.voltage, 'watt': d.watt,
            'status': d.status,
        } for d in reversed(list(data))]
        # reversed() — 응답에선 시간 오름차순(과거→현재)으로 뒤집어 보냄
        # 차트가 왼쪽=과거, 오른쪽=현재 표시하는 일반적 컨벤션에 맞춤
        # ⚠️ list()로 한 번에 끌어오고 reversed — limit이 클 때 메모리 부담
        #    .order_by('timestamp')[:limit] 한 번 더 정렬이 더 ORM스러움

        return Response({'device_id': device_id, 'data': result})

    # ─── 생성 ───
    def post(self, request):
        # 외부 센서가 측정값을 보내올 때의 진입점 — 시스템의 핵심 데이터 수신구
        device_id = request.data.get('device_id')
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({'error': '센서 없음'}, status=http_status.HTTP_404_NOT_FOUND)

        # sensor_type 추출 — 명시되지 않으면 Device.sensor_type 으로 fallback
        sensor_type = request.data.get('sensor_type') or device.sensor_type
        # 하위 호환 — 옛날 클라이언트가 sensor_type 안 보내도 Device 등록 시점 종류로 처리

        def _get_float(key):
            # request.data에서 안전하게 float 추출하는 클로저
            # None은 None으로 보존 (해당 가스/필드 측정 안 됨), 값이 있으면 float 변환
            v = request.data.get(key)
            return float(v) if v is not None else None
            # ⚠️ 'abc' 같은 비숫자 문자열 들어오면 ValueError 발생 → 500 에러
            #    try/except로 보호 권장

        # ═══════════════════════════════════════════════════
        # 분기: gas / power 별로 파싱 + 판정 + 저장
        # ═══════════════════════════════════════════════════
        if sensor_type == 'gas':
            sd, s, payload_values = self._save_gas(device, _get_float)
            # sd: SensorData 인스턴스, s: status 판정, payload_values: WS push용 dict
        elif sensor_type == 'power':
            sd, s, payload_values = self._save_power(device, _get_float)
        else:
            return Response(
                {'error': f'미지원 sensor_type: {sensor_type}'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
            # temperature, motion 타입은 아직 수신 처리 미구현

        # ═══════════════════════════════════════════════════
        # 공통: Device 상태 갱신 + WS push
        # ═══════════════════════════════════════════════════
        device.status = s
        # Device의 최신 상태를 이번 판정 결과로 갱신 — 지도 마커 색상 결정 데이터
        device.save(update_fields=['status', 'last_value'])
        # 두 필드만 UPDATE — 효율적 (geofence FK 등 다른 필드는 안 건드림)
        # _save_gas/_save_power가 device.last_value를 미리 set함

        publish_sensor_update({
            # WebSocket 채널로 모든 대시보드 클라이언트에 즉시 전송
            "device_id":   device.device_id,
            "sensor_type": sensor_type,
            "status":      s,
            "values":      payload_values,
            # gas는 9종 dict, power는 3종 dict — 클라이언트가 종류별로 파싱
            "timestamp":   sd.timestamp.isoformat(),
            # ISO 8601 형식 — 클라이언트 JS가 new Date()로 파싱 가능
        })

        return Response(
            {'id': sd.id, 'status': s},
            # 최소 응답 — 외부 센서가 받을 정보는 ID와 판정 결과면 충분
            status=http_status.HTTP_201_CREATED,
        )

    # ─── 가스 저장 ───
    def _save_gas(self, device, _get_float):
        # gas 타입 측정값 파싱 + 판정 + DB 저장 — post()에서 호출되는 헬퍼
        gas = {
            # 9종 가스를 dict로 모아 classify_gas에 전달할 형태로 정리
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
        # 9종 중 worst-case 1개를 'normal'/'caution'/'danger'로 압축

        sd = SensorData.objects.create(
            # DB INSERT 1건 — 측정 시각은 auto_now_add로 자동
            device=device,
            co=gas['co'],   h2s=gas['h2s'], co2=gas['co2'], o2=gas['o2'],
            no2=gas['no2'], so2=gas['so2'], o3=gas['o3'],
            nh3=gas['nh3'], voc=gas['voc'],
            status=s,
            # 판정 결과를 측정값과 함께 저장 — 이후 다시 분류할 필요 없음
        )
        # 지도 마커용 대표값: CO
        if gas['co'] is not None:
            device.last_value = gas['co']
            # 9종 중 CO를 대표값으로 — 일산화탄소가 가장 흔한 산업 위험 가스라는 도메인 지식
            # ⚠️ CO 측정 안 되고 다른 가스만 있을 땐 last_value 갱신 안 됨 → 옛 값 표시 위험
        return sd, s, gas

    # ─── 전력 저장 ───
    def _save_power(self, device, _get_float):
        # power 타입 측정값 파싱 + 판정 + DB 저장
        power = {
            'current': _get_float('current'),
            'voltage': _get_float('voltage'),
            'watt':    _get_float('watt'),
        }
        # 판정 — 동적 24h 중앙값 기반 (device_id 전달 필수)
        s = classify_power(power, device.device_id)
        # device_id 없으면 동적 판정 못 함 → 고정 임계치 fallback
        # 여기선 device.device_id가 항상 있으므로 동적 판정 활성화

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
            # 전력은 Watt가 가장 직관적인 표시값
        return sd, s, power