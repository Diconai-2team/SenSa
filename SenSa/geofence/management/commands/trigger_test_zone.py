"""
관리 명령: 검증용 동적 zone 수동 트리거.

[v2 패치]
초기 반경이 작아 이웃 센서 (가장 가까워도 100px+) 를 못 잡는 문제 발생.
--initial-elapsed 옵션으로 초기 가상 경과 시간을 늘려 더 큰 반경으로 생성 가능.

사용:
    python manage.py trigger_test_zone --device sensor_01 --gas co
    python manage.py trigger_test_zone --device sensor_01 --gas co --initial-elapsed 120
    python manage.py trigger_test_zone --device sensor_01 --gas co --severity danger
"""
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from devices.models import Device
from geofence.zone_lifecycle import create_dynamic_zone, update_zone_radius


SEVERITY_TO_RISK_LEVEL = {
    'warning':  'medium',
    'danger':   'high',
    'critical': 'critical',
}


class Command(BaseCommand):
    help = '검증용 동적 위험 zone 수동 트리거 생성'

    def add_arguments(self, parser):
        parser.add_argument('--device', required=True, help='Device.device_id')
        parser.add_argument('--gas', default='co', help='가스 종류')
        parser.add_argument(
            '--severity',
            default='warning',
            choices=['warning', 'danger', 'critical'],
            help='위험 단계',
        )
        parser.add_argument(
            '--source',
            default='manual',
            choices=['manual', 'threshold', 'ttm_anomaly', 'ttm_forecast'],
            help='발동 원인',
        )
        parser.add_argument(
            '--initial-elapsed', type=float, default=None,
            help='초기 가상 경과 시간 (초). 큰 값일수록 초기 반경이 큼. '
                 '미지정 시 기본값 10초 사용.',
        )

    def handle(self, *args, **options):
        device_id = options['device']
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            raise CommandError(f"device_id='{device_id}' 를 찾을 수 없음")

        risk_level = SEVERITY_TO_RISK_LEVEL[options['severity']]

        zone = create_dynamic_zone(
            source_device=device,
            gas_type=options['gas'],
            trigger_source=options['source'],
            risk_level=risk_level,
        )

        # --initial-elapsed 옵션 처리: created_at 을 N초 전으로 강제 + 반경 갱신
        elapsed = options['initial_elapsed']
        if elapsed is not None and elapsed > 0:
            past = timezone.now() - timedelta(seconds=elapsed)
            zone.created_at = past
            zone.save()
            update_zone_radius(zone)
            zone.refresh_from_db()

        self.stdout.write(self.style.SUCCESS(
            f"\n동적 zone 생성됨\n"
            f"  zone_id:      {zone.id}\n"
            f"  name:         {zone.name}\n"
            f"  source:       {device.device_id} ({device.x}, {device.y})\n"
            f"  gas_type:     {zone.gas_type}\n"
            f"  tier:         {zone.tier}\n"
            f"  radius:       {zone.current_radius_px:.1f}px\n"
            f"  polygon:      {len(zone.polygon)}개 점\n"
            f"  expires_at:   {zone.expires_at}\n"
        ))
