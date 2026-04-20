"""
seed_data.py — 더미 데이터 생성 커맨드

사용법: python manage.py seed_data

생성 대상:
  - Device   5개 (가스 3 + 전력 2)
  - GeoFence 2개 (위험 + 주의 구역)
  - Worker   5개 (현장 작업자)    ← 신규 추가

위치: dashboard/management/commands/seed_data.py
      (또는 monitor/management/commands/seed_data.py — 앱 이름에 따라)

※ 여러 번 실행해도 중복 생성되지 않음 (update_or_create 사용)
"""
from django.core.management.base import BaseCommand
from devices.models import Device
from geofence.models import GeoFence
from workers.models import Worker      # ← 신규 import


# ── 센서 장비 시드 ──
# JS의 SENSOR_DEVICES 배열과 device_id가 일치해야 함
DUMMY_DEVICES = [
    {"device_id": "sensor_01", "device_name": "가스센서 A", "sensor_type": "gas",
     "x": 200, "y": 150, "status": "normal", "last_value": 12.3, "last_value_unit": "ppm"},
    {"device_id": "sensor_02", "device_name": "가스센서 B", "sensor_type": "gas",
     "x": 500, "y": 180, "status": "normal", "last_value": 8.1, "last_value_unit": "ppm"},
    {"device_id": "sensor_03", "device_name": "가스센서 C", "sensor_type": "gas",
     "x": 350, "y": 390, "status": "normal", "last_value": 600, "last_value_unit": "ppm"},
    {"device_id": "power_01", "device_name": "스마트파워 A", "sensor_type": "power",
     "x": 620, "y": 100, "status": "normal", "last_value": 220.0, "last_value_unit": "V"},
    {"device_id": "power_02", "device_name": "스마트파워 B", "sensor_type": "power",
     "x": 130, "y": 390, "status": "normal", "last_value": 218.5, "last_value_unit": "V"},
]

# ── 지오펜스 시드 ──
# polygon 좌표는 [x, y] 형태 (Leaflet Simple CRS 기준)
DUMMY_FENCES = [
    {
        "name": "고온구역 A",
        "zone_type": "danger",
        "risk_level": "critical",
        "description": "고온 장비 밀집 구역. 보호장구 필수.",
        "polygon": [[100, 100], [300, 100], [300, 300], [100, 300]],
    },
    {
        "name": "주의구역 B",
        "zone_type": "caution",
        "risk_level": "medium",
        "description": "화학물질 보관 인근 구역.",
        "polygon": [[400, 200], [600, 200], [600, 400], [400, 400]],
    },
]

# ── 작업자 시드 (신규) ──
# worker_01, worker_02는 JS의 WORKERS 배열과 ID가 일치
# → 4차에서 FK 전환 시 자연스럽게 연결됨
DUMMY_WORKERS = [
    {"worker_id": "worker_01", "name": "작업자 A", "department": "생산1팀"},
    {"worker_id": "worker_02", "name": "작업자 B", "department": "생산1팀"},
    {"worker_id": "worker_03", "name": "작업자 C", "department": "설비팀"},
    {"worker_id": "worker_04", "name": "작업자 D", "department": "안전관리팀"},
    {"worker_id": "worker_05", "name": "작업자 E", "department": "생산2팀"},
]


class Command(BaseCommand):
    """
    BaseCommand를 상속하면 manage.py 커맨드가 됨

    파일 위치: 앱/management/commands/seed_data.py
    실행: python manage.py seed_data
    """
    help = '더미 센서, 지오펜스, 작업자 데이터를 생성합니다.'

    def handle(self, *args, **kwargs):
        """
        manage.py seed_data 실행 시 호출되는 메서드
        """

        # ═══════════════════════════════════════
        # Device 시드
        # ═══════════════════════════════════════
        device_created = 0
        for d in DUMMY_DEVICES:
            # ── update_or_create(조건, defaults=데이터) ──
            #
            # 1. device_id로 DB에서 찾음
            # 2. 있으면 → defaults 값으로 업데이트
            # 3. 없으면 → 새로 생성
            #
            # 반환값: (객체, 생성여부)
            # _는 객체를 안 쓸 때 관례적 변수명
            _, is_new = Device.objects.update_or_create(
                device_id=d['device_id'],   # 조건: 이 device_id로 찾아봐
                defaults=d                   # 데이터: 나머지 필드 전부
            )
            if is_new:
                device_created += 1

        # self.stdout.write → 터미널에 출력
        # self.style.SUCCESS → 초록색 텍스트
        self.stdout.write(self.style.SUCCESS(
            f'센서 {device_created}개 생성 (총 {len(DUMMY_DEVICES)}개 upsert)'
        ))

        # ═══════════════════════════════════════
        # GeoFence 시드
        # ═══════════════════════════════════════
        fence_created = 0
        for f in DUMMY_FENCES:
            # 이름으로 중복 체크 (update_or_create 대신 exists 사용)
            if not GeoFence.objects.filter(name=f['name']).exists():
                GeoFence.objects.create(**f)
                # **f → 딕셔너리를 키워드 인자로 풀어서 전달
                # GeoFence.objects.create(name="고온구역 A", zone_type="danger", ...)
                fence_created += 1

        self.stdout.write(self.style.SUCCESS(
            f'지오펜스 {fence_created}개 생성'
        ))

        # ═══════════════════════════════════════
        # Worker 시드 (신규)
        # ═══════════════════════════════════════
        worker_created = 0
        for w in DUMMY_WORKERS:
            _, is_new = Worker.objects.update_or_create(
                worker_id=w['worker_id'],   # 조건
                defaults=w                   # 데이터
            )
            if is_new:
                worker_created += 1

        self.stdout.write(self.style.SUCCESS(
            f'작업자 {worker_created}개 생성 (총 {len(DUMMY_WORKERS)}개 upsert)'
        ))