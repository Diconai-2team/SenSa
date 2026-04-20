from django.core.management.base import BaseCommand
from monitor.models import Device, GeoFence


DUMMY_DEVICES = [
    {"device_id": "sensor_01", "device_name": "가스센서 A", "sensor_type": "gas",
     "x": 200, "y": 150, "status": "normal", "last_value": 12.3, "last_value_unit": "ppm"},
    {"device_id": "sensor_02", "device_name": "가스센서 B", "sensor_type": "gas",
     "x": 500, "y": 300, "status": "caution", "last_value": 45.7, "last_value_unit": "ppm"},
    {"device_id": "sensor_03", "device_name": "전력센서 A", "sensor_type": "power",
     "x": 350, "y": 200, "status": "normal", "last_value": 220.0, "last_value_unit": "V"},
    {"device_id": "sensor_04", "device_name": "온도센서 A", "sensor_type": "temperature",
     "x": 150, "y": 400, "status": "danger", "last_value": 89.2, "last_value_unit": "°C"},
    {"device_id": "sensor_05", "device_name": "동작감지 A", "sensor_type": "motion",
     "x": 600, "y": 450, "status": "normal", "last_value": 0.0, "last_value_unit": ""},
]

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


class Command(BaseCommand):
    help = '더미 센서 및 지오펜스 데이터를 생성합니다.'

    def handle(self, *args, **kwargs):
        created = 0
        for d in DUMMY_DEVICES:
            obj, is_new = Device.objects.update_or_create(
                device_id=d['device_id'], defaults=d
            )
            if is_new:
                created += 1

        self.stdout.write(self.style.SUCCESS(f'센서 {created}개 생성 (총 {len(DUMMY_DEVICES)}개 upsert)'))

        fence_created = 0
        for f in DUMMY_FENCES:
            if not GeoFence.objects.filter(name=f['name']).exists():
                GeoFence.objects.create(**f)
                fence_created += 1

        self.stdout.write(self.style.SUCCESS(f'지오펜스 {fence_created}개 생성'))