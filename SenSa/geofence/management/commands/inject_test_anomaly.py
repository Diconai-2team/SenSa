"""
관리 명령: 검증용 가짜 SensorData 주입.

[v2 패치]
SensorData.timestamp 가 auto_now_add 라 시간이 흐른 뒤 tick 호출 시
LOOKBACK_RECENT_SEC(60초) 윈도우를 벗어나 baseline 쪽으로 분류되는 문제 발생.

해결: --offset-seconds 옵션으로 timestamp 를 강제 설정 (기본 0 = 지금).
검증 흐름:
    1. inject (--offset 5 → 5초 전으로 주입)
    2. 즉시 tick → 최근 윈도우 안에 들어감
    3. 잔차 검출 → 승격

사용:
    python manage.py inject_test_anomaly --device sensor_02 --gas co --value 50
    python manage.py inject_test_anomaly --device sensor_02 --gas co --value 50 --offset 10 --count 5
"""
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from devices.models import Device, SensorData


class Command(BaseCommand):
    help = '검증용 이상값 SensorData 주입 (timestamp 강제 설정)'

    def add_arguments(self, parser):
        parser.add_argument('--device', required=True, help='Device.device_id')
        parser.add_argument('--gas', default='co', help='가스 종류')
        parser.add_argument(
            '--value', type=float, required=True,
            help='주입할 측정값 (ppm)',
        )
        parser.add_argument(
            '--count', type=int, default=3,
            help='연속 주입 건수 (기본 3)',
        )
        parser.add_argument(
            '--offset', type=int, default=0,
            help='timestamp 를 N 초 전으로 설정 (기본 0 = 지금). '
                 '여러 건 주입 시 마지막 건이 N초 전, 그 이전 건들은 더 앞.',
        )

    def handle(self, *args, **options):
        device_id = options['device']
        gas = options['gas'].lower()
        value = options['value']
        count = options['count']
        offset = options['offset']

        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            raise CommandError(f"device_id='{device_id}' 를 찾을 수 없음")

        valid_fields = {
            'co', 'h2s', 'co2', 'o2', 'no2', 'so2', 'o3', 'nh3', 'voc',
        }
        if gas not in valid_fields:
            raise CommandError(f"gas='{gas}' 미지원. 가능: {sorted(valid_fields)}")

        now = timezone.now()
        created_ids = []
        for i in range(count):
            sd = SensorData.objects.create(
                device=device, status='caution',
                **{gas: value},
            )
            # auto_now_add 우회 — timestamp 강제 설정
            #   마지막 건이 offset 초 전, 그 이전 건들은 더 앞 (1초씩 간격)
            seconds_ago = offset + (count - 1 - i)
            stamp = now - timedelta(seconds=seconds_ago)
            SensorData.objects.filter(pk=sd.pk).update(timestamp=stamp)
            created_ids.append(sd.pk)

        self.stdout.write(self.style.SUCCESS(
            f"\n주입 완료\n"
            f"  device:        {device.device_id}\n"
            f"  gas:           {gas}\n"
            f"  value:         {value}\n"
            f"  count:         {len(created_ids)}\n"
            f"  timestamp 범위: {offset + count - 1}초 전 ~ {offset}초 전\n"
        ))
