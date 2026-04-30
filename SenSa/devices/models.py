"""
devices/models.py — 센서 장비 + 측정값 히스토리

[변경 이력]
  Phase A: 초기 4종 가스 필드 (co, h2s, co2, o2) + temperature
  Gas 병합: Device.geofence FK + 9종 가스 필드 (no2, so2, o3, nh3, voc)
  Power 병합 (본 커밋): SensorData 에 전력 3필드 (current, voltage, watt)
    → 동적 전력 판정(최근 24시간 중앙값 기반)의 데이터 소스.
    → alerts.services._get_24h_avg_watt 가 이 watt 필드를 읽음.
"""

from django.db import models
# 모델 필드 타입(CharField, FloatField, ForeignKey 등)을 정의하기 위한 ORM 모듈


SENSOR_TYPE_CHOICES = [
# Device.sensor_type 필드의 선택 가능한 값 — 센서를 종류별로 분류
    ('gas', '가스'),
    # 9종 가스 측정 센서 — co, h2s, co2, o2, no2, so2, o3, nh3, voc
    ('power', '전력'),
    # 전력 측정 센서 — current, voltage, watt (Power 병합 신규)
    ('temperature', '온도'),
    # 온도 센서 — 현재 알람 판정엔 미사용 (legacy)
    ('motion', '동작'),
    # 동작 감지 센서 — 향후 확장용 (현재 미사용)
]

STATUS_CHOICES = [
# Device.status / SensorData.status 공통 — 센서 1개의 상태 분류
# alerts.state_store의 sensor 상태와 동일한 3단계 (작업자는 4단계로 critical 추가)
    ('normal', '정상'),
    # 임계치 미만 — 알람 발생 안 함
    ('caution', '주의'),
    # caution 임계치 도달 — STEL 등 단시간 노출 한계
    ('danger', '위험'),
    # danger 임계치 도달 — IDLH 등 즉시 대피 필요
]


class Device(models.Model):
    """센서 디바이스 — x, y는 이미지 내부 좌표"""
    # 물리적 센서 1개를 나타내는 엔티티 — 위치(x,y)는 공장 평면도 이미지 내 픽셀 좌표
    
    device_id       = models.CharField(max_length=50, unique=True)
    # 센서 식별자 — 'sensor_01', 'power_03' 등 사람이 읽는 ID
    # unique=True — DB 레벨에서 중복 차단 + 자동 인덱스 생성
    # SensorData/Alarm/state_store가 모두 이 값으로 센서를 참조 (FK 대신 문자열로 느슨하게 연결)
    device_name     = models.CharField(max_length=100)
    # 센서 표시명 — '1번 라인 가스 센서', '용접실 전력 모니터' 등 한국어 이름
    sensor_type     = models.CharField(max_length=20, choices=SENSOR_TYPE_CHOICES, default='gas')
    # 센서 종류 — views.SensorDataView가 gas/power 분기 처리할 때 기준
    # default='gas' — 초기 시스템이 가스 중심이었던 흔적 (Phase A 시점 기본값)
    x               = models.FloatField(default=0)
    # 평면도 이미지 내 X 좌표 (픽셀) — geofence.point_in_polygon 판정에 사용
    y               = models.FloatField(default=0)
    # 평면도 이미지 내 Y 좌표 (픽셀)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='normal')
    # 센서의 현재 상태 — 마지막 측정값 기준으로 SensorDataView.post가 갱신
    # ⚠️ DB의 이 필드와 alerts.state_store의 Redis 상태는 별개 — Redis가 Hysteresis 상태 관리
    last_value      = models.FloatField(null=True, blank=True)
    # 지도 마커에 표시할 대표값 — 가스면 CO 농도, 전력이면 watt
    # 9종 가스를 한 화면에 다 못 표시하니 "가장 중요한 1개"를 골라 캐싱
    last_value_unit = models.CharField(max_length=20, blank=True, default='')
    # 대표값의 단위 — 'ppm', 'W' 등 (UI 표시용)
    is_active       = models.BooleanField(default=True)
    # 센서 활성화 여부 — False면 ViewSet의 queryset에서 제외 (논리적 삭제)
    # 물리 삭제 안 하는 이유: SensorData FK가 CASCADE라 측정 히스토리도 같이 날아감

    # ── 소속 지오펜스 (Gas 병합) ──
    # null=True             → 바깥 공용 구역 센서도 허용
    # on_delete=SET_NULL    → 지오펜스 삭제해도 센서는 남음
    # related_name='devices'→ geofence.devices.all() 로 역참조 가능
    geofence = models.ForeignKey(
        'geofence.GeoFence',
        # 문자열 참조 — geofence 앱과의 순환 import 회피
        on_delete=models.SET_NULL,
        # 지오펜스 삭제돼도 센서는 살아남고 FK만 NULL — 데이터 보존 우선
        null=True, blank=True,
        # null=True: DB에서 NULL 허용 / blank=True: 폼/시리얼라이저에서 빈 값 허용
        related_name='devices',
        # 역참조 이름 — geofence.devices.all()로 해당 지오펜스 소속 센서 조회 가능
        # alerts.services._find_sensor_geofence가 1순위로 이 FK 사용
        help_text='이 센서가 속한 지오펜스 (없으면 공용 구역)',
        # admin 폼에 표시되는 안내 — 운영자에게 NULL의 의미를 명시
    )

    class Meta:
        ordering = ['device_id']
        # 기본 정렬 — device_id 알파벳순 (sensor_01, sensor_02, ... 자연스러운 순서)

    def __str__(self):
        # admin/shell에서 객체를 읽기 좋은 형태로 표시
        return f"{self.device_name} ({self.device_id})"
        # '1번 라인 가스 센서 (sensor_01)' 형태


class SensorData(models.Model):
    """
    센서 측정값 히스토리 — 9종 가스 + 전력 3필드 + 온도

    가스 9종 (Gas 전담 팀원 정의):
      co, h2s, co2, o2, no2, so2, o3, nh3, voc

    전력 3종 (Power 병합):
      current — 전류 (A)
      voltage — 전압 (V)
      watt    — 전력 (W)
      → classify_power 의 24시간 중앙값 동적 임계치 계산의 원천 데이터
    """
    # 센서 측정값 1건을 저장하는 시계열 테이블 — POST /sensor-data/ 호출마다 1행 INSERT
    # ⚠️ wide table 패턴 — 가스/전력을 한 테이블에 합쳐 빈 컬럼이 다수 발생
    #    초당 누적되므로 운영 환경에선 파티셔닝/아카이빙 전략 필요

    device      = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='data')
    # 어느 센서가 측정한 값인지 FK
    # CASCADE — Device 삭제 시 측정 히스토리도 함께 삭제 (정합성 우선)
    # related_name='data' — device.data.all()로 해당 센서의 모든 측정값 조회 가능

    # ─── 가스 9종 ───
    co          = models.FloatField(null=True, blank=True, help_text='일산화탄소 (ppm)')
    # 일산화탄소 농도 — ACGIH TWA 25ppm / NIOSH Ceiling 200ppm 기준
    h2s         = models.FloatField(null=True, blank=True, help_text='황화수소 (ppm)')
    # 황화수소 농도 — KOSHA 적정공기 10ppm / IDLH 50ppm
    co2         = models.FloatField(null=True, blank=True, help_text='이산화탄소 (ppm)')
    # 이산화탄소 농도 — 실내공기질 1000ppm / TWA 5000ppm
    o2          = models.FloatField(null=True, blank=True, help_text='산소 (%), 구간형 판정')
    # 산소 농도 — %, alerts.services.classify_gas에서 양방향 임계 (16~23.5%) 처리
    # 다른 가스와 달리 너무 낮아도 너무 높아도 위험 (구간형)
    no2         = models.FloatField(null=True, blank=True, help_text='이산화질소 (ppm)')
    # 이산화질소 — 고용노동부 TWA 3ppm / STEL 5ppm
    so2         = models.FloatField(null=True, blank=True, help_text='이산화황 (ppm)')
    # 이산화황 — 고용노동부 TWA 2ppm / STEL 5ppm
    o3          = models.FloatField(null=True, blank=True, help_text='오존 (ppm)')
    # 오존 — ACGIH TLV 0.05~0.1ppm
    nh3         = models.FloatField(null=True, blank=True, help_text='암모니아 (ppm)')
    # 암모니아 — ACGIH TWA 25ppm / 고노출 50ppm
    voc         = models.FloatField(null=True, blank=True, help_text='유기화합물 (ppm)')
    # 휘발성 유기화합물 (TVOC) — 실내기준 0.5~2.0ppm

    # ─── 전력 3종 (Power 병합) ───
    current     = models.FloatField(null=True, blank=True, help_text='전류 (A)')
    # 전류 (Ampere) — 고정 임계치 fallback 시 사용 (15A caution / 25A danger)
    voltage     = models.FloatField(null=True, blank=True, help_text='전압 (V)')
    # 전압 (Volt) — 220V±10% 벗어나면 항상 danger (동적 판정 우회)
    watt        = models.FloatField(null=True, blank=True, help_text='전력 (W)')
    # 전력 (Watt) — alerts.services._get_24h_avg_watt가 이 필드의 24h 중앙값 계산
    # 동적 판정의 핵심 데이터 — null이면 동적 판정 스킵하고 fallback

    # ─── 기타 ───
    temperature = models.FloatField(null=True, blank=True)
    # 온도 — Phase A부터 있던 필드 (현재 알람 판정엔 미사용, legacy)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='normal')
    # 이 측정값 1건의 판정 결과 — classify_gas/classify_power의 반환값 저장
    # SensorDataView.post가 INSERT 시점에 한 번만 결정하고 이후 불변
    timestamp   = models.DateTimeField(auto_now_add=True)
    # 측정 수신 시각 — auto_now_add로 INSERT 시 자동 채움 (수정 불가)
    # ⚠️ 센서가 측정한 시각이 아니라 서버가 받은 시각 — 네트워크 지연 시 차이 발생 가능

    class Meta:
        ordering = ['-timestamp']
        # 기본 정렬: 최신 측정값이 먼저 — 대시보드 차트 데이터 순서와 일치
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            # 복합 인덱스 — "특정 센서의 최근 N건" 쿼리 최적화
            # SensorDataView.get의 SensorData.objects.filter(device=device)[:limit] 핫패스
            # alerts.services._get_24h_avg_watt의 device + timestamp 필터 핫패스
        ]

    def __str__(self):
        return f"{self.device.device_name} @ {self.timestamp}"
        # ⚠️ device.device_name 접근 — N+1 위험. admin 목록에서 select_related 권장
