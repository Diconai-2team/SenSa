"""
seed_data.py — 더미 데이터 생성 커맨드

사용법: python manage.py seed_data

[변경 이력]
  Phase A: Device 5개 + GeoFence 2개 + Worker 5개
  Gas 병합 (본 커밋):
    - GeoFence 시드 제거 → admin 에서 직접 등록한 것을 사용
      (배경 이미지·시나리오에 따라 polygon 좌표가 바뀌므로 시드 부적합)
    - Device 에 geofence FK 자동 할당
      좌표와 GeoFence.polygon 의 point_in_polygon 판정
    - zone_type 우선순위 (danger > restricted > caution) 로 다중 포함 시 해결

※ 여러 번 실행해도 중복 생성되지 않음 (update_or_create 사용)
"""

from django.core.management.base import BaseCommand

from devices.models import Device
from geofence.models import GeoFence
from geofence.services import point_in_polygon
from workers.models import Worker


# ── 센서 장비 시드 ──
# JS 의 SENSOR_DEVICES 배열과 device_id 일치 (front/back 좌표 정합)
# geofence 는 아래에서 좌표 기반으로 자동 할당 (여기서 지정 안 함)
DUMMY_DEVICES = [
    {
        "device_id": "sensor_01",
        "device_name": "가스센서 A",
        "sensor_type": "gas",
        "x": 200,
        "y": 150,
        "status": "normal",
        "last_value": 12.3,
        "last_value_unit": "ppm",
    },
    {
        "device_id": "sensor_02",
        "device_name": "가스센서 B",
        "sensor_type": "gas",
        "x": 500,
        "y": 180,
        "status": "normal",
        "last_value": 8.1,
        "last_value_unit": "ppm",
    },
    {
        "device_id": "sensor_03",
        "device_name": "가스센서 C",
        "sensor_type": "gas",
        "x": 350,
        "y": 390,
        "status": "normal",
        "last_value": 600,
        "last_value_unit": "ppm",
    },
    {
        "device_id": "power_01",
        "device_name": "스마트파워 A",
        "sensor_type": "power",
        "x": 620,
        "y": 100,
        "status": "normal",
        "last_value": 220.0,
        "last_value_unit": "V",
    },
    {
        "device_id": "power_02",
        "device_name": "스마트파워 B",
        "sensor_type": "power",
        "x": 130,
        "y": 390,
        "status": "normal",
        "last_value": 218.5,
        "last_value_unit": "V",
    },
]

# ── 작업자 시드 ──
# worker_01~05: JS 의 WORKERS 배열과 ID 일치
DUMMY_WORKERS = [
    {"worker_id": "worker_01", "name": "작업자 A", "department": "생산1팀"},
    {"worker_id": "worker_02", "name": "작업자 B", "department": "생산1팀"},
    {"worker_id": "worker_03", "name": "작업자 C", "department": "설비팀"},
    {"worker_id": "worker_04", "name": "작업자 D", "department": "안전관리팀"},
    {"worker_id": "worker_05", "name": "작업자 E", "department": "생산2팀"},
]

# ── zone_type 우선순위 ──
# 여러 지오펜스에 동시에 속할 때 더 심각한 것 선택
# (예: 주의구역 안에 위험구역이 겹쳐 있으면 위험 쪽으로 판정)
ZONE_PRIORITY = {
    "danger": 3,
    "restricted": 2,
    "caution": 1,
}


def find_best_geofence(x, y, fences):
    """(x, y) 를 포함하는 지오펜스 중 zone_type 우선순위가 가장 높은 것 반환."""
    matches = [
        f
        for f in fences
        if f.polygon and len(f.polygon) >= 3 and point_in_polygon(x, y, f.polygon)
    ]
    if not matches:
        return None
    matches.sort(key=lambda f: ZONE_PRIORITY.get(f.zone_type, 0), reverse=True)
    return matches[0]


class Command(BaseCommand):
    help = "더미 센서, 작업자 데이터를 생성하고 센서에 지오펜스를 자동 할당합니다."

    def handle(self, *args, **kwargs):

        # ═══════════════════════════════════════
        # GeoFence 로드 (시드 아님 — admin 등록본 사용)
        # ═══════════════════════════════════════
        fences = list(GeoFence.objects.filter(is_active=True))
        self.stdout.write(f"활성 GeoFence: {len(fences)}개 (admin 에서 등록된 것 사용)")

        if not fences:
            self.stdout.write(
                self.style.WARNING(
                    "⚠ 활성 GeoFence 가 없습니다. admin 에서 먼저 등록하세요. "
                    "센서는 geofence=null 로 생성됩니다."
                )
            )

        # ═══════════════════════════════════════
        # Device 시드 + geofence 자동 할당
        # ═══════════════════════════════════════
        device_created = 0
        self.stdout.write("─" * 60)

        for d in DUMMY_DEVICES:
            # 좌표로 geofence 자동 판정
            matched_fence = find_best_geofence(d["x"], d["y"], fences)

            # defaults 에 geofence FK 포함
            defaults = {**d, "geofence": matched_fence}

            obj, is_new = Device.objects.update_or_create(
                device_id=d["device_id"],
                defaults=defaults,
            )
            if is_new:
                device_created += 1

            action = "신규" if is_new else "갱신"
            fence_info = (
                f"→ [{matched_fence.zone_type}] {matched_fence.name}"
                if matched_fence
                else "→ (공용 구역)"
            )
            self.stdout.write(
                f"  [{action}] {d['device_id']:12s} @ ({d['x']:4d}, {d['y']:4d}) {fence_info}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"센서 {device_created}개 생성 (총 {len(DUMMY_DEVICES)}개 upsert)"
            )
        )

        # ═══════════════════════════════════════
        # Worker 시드
        # ═══════════════════════════════════════
        worker_created = 0
        for w in DUMMY_WORKERS:
            _, is_new = Worker.objects.update_or_create(
                worker_id=w["worker_id"],
                defaults=w,
            )
            if is_new:
                worker_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"작업자 {worker_created}개 생성 (총 {len(DUMMY_WORKERS)}개 upsert)"
            )
        )

        self.stdout.write("─" * 60)
        self.stdout.write(self.style.SUCCESS("✓ 시드 완료"))
