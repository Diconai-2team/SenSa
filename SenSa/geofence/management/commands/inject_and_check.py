"""
관리 명령: 다중 센서 spike 주입 + 즉시 tick (Phase C 검증 통합).

[v2] baseline 자동 주입 옵션 추가.
운영 환경에서는 fastapi_generator 가 평소 정상값을 지속 흘리므로
baseline 데이터가 자연히 쌓이지만, 시연·검증 환경에서는 그렇지 않을 수 있음.
--with-baseline 옵션으로 정상값을 baseline 윈도우 (5~30분 전) 에 자동 주입.

사용:
    # spike 만 주입 (기존 동작 — baseline 충분 시)
    python manage.py inject_and_check -d sensor_03 -g co -v 100

    # baseline 까지 자동 주입 (시연·검증 권장)
    python manage.py inject_and_check -d sensor_02 sensor_03 sensor_04 \\
        -g co -v 100 --with-baseline --baseline-value 12
"""
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from devices.models import Device, SensorData
from geofence.zone_lifecycle import tick


VALID_GASES = {
    'co', 'h2s', 'co2', 'o2', 'no2', 'so2', 'o3', 'nh3', 'voc',
}


class Command(BaseCommand):
    help = '다중 센서 spike 주입 + 즉시 tick (검증 통합, baseline 자동 옵션)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--devices',
            nargs='+', required=True,
            help='대상 센서 device_id 목록 (공백 구분)',
        )
        parser.add_argument(
            '--gas',
            default='co',
            help='가스 종류 (기본 co)',
        )
        parser.add_argument(
            '--value',
            type=float, default=100.0,
            help='spike 주입 값 (기본 100)',
        )
        parser.add_argument(
            '--count',
            type=int, default=3,
            help='센서당 spike 주입 건수 (기본 3)',
        )
        parser.add_argument(
            '--with-baseline',
            action='store_true',
            help='baseline 윈도우 (5~30분 전) 에 정상값 자동 주입',
        )
        parser.add_argument(
            '--baseline-value',
            type=float, default=12.0,
            help='baseline 정상값 (기본 12 — CO 평탄 구간 수준)',
        )
        parser.add_argument(
            '--baseline-count',
            type=int, default=10,
            help='baseline 주입 건수 (기본 10)',
        )

    def handle(self, *args, **options):
        device_ids = options['devices']
        gas = options['gas'].lower()
        value = options['value']
        count = options['count']
        with_baseline = options['with_baseline']
        baseline_value = options['baseline_value']
        baseline_count = options['baseline_count']

        if gas not in VALID_GASES:
            raise CommandError(f"gas='{gas}' 미지원. 가능: {sorted(VALID_GASES)}")

        devices = []
        for did in device_ids:
            try:
                devices.append(Device.objects.get(device_id=did))
            except Device.DoesNotExist:
                raise CommandError(f"device_id='{did}' 를 찾을 수 없음")

        now = timezone.now()

        # ── (선택) baseline 정상값 주입 ──
        baseline_injected = 0
        if with_baseline:
            for device in devices:
                for i in range(baseline_count):
                    sd = SensorData.objects.create(
                        device=device, status='normal',
                        **{gas: baseline_value},
                    )
                    # 500~1700초 전 사이로 분산 (baseline 윈도우 안)
                    seconds_ago = 500 + i * 120
                    stamp = now - timedelta(seconds=seconds_ago)
                    SensorData.objects.filter(pk=sd.pk).update(timestamp=stamp)
                    baseline_injected += 1
            self.stdout.write(
                f"\n[0/2] baseline 주입: {len(devices)} × {baseline_count} "
                f"= {baseline_injected}건 ({baseline_value}{gas})"
            )

        # ── spike 주입 (5초 전 ~ 5+count 초 전) ──
        spike_injected = 0
        for device in devices:
            for i in range(count):
                sd = SensorData.objects.create(
                    device=device, status='caution',
                    **{gas: value},
                )
                seconds_ago = 5 + (count - 1 - i)
                stamp = now - timedelta(seconds=seconds_ago)
                SensorData.objects.filter(pk=sd.pk).update(timestamp=stamp)
                spike_injected += 1

        self.stdout.write(
            f"\n[1/2] spike 주입: {len(devices)} × {count} "
            f"= {spike_injected}건 ({value}{gas})"
        )

        # ── 즉시 tick ──
        result = tick(check_upgrade=True)

        self.stdout.write(
            f"\n[2/2] tick 결과:\n"
            f"  반경 갱신:    {result['updated']}\n"
            f"  만료:         {result['expired']}\n"
            f"  확인 승격:    {result['upgraded_to_confirmed']}\n"
            f"  긴급 승격:    {result['upgraded_to_critical']}"
        )

        if result['upgraded_to_confirmed'] or result['upgraded_to_critical']:
            self.stdout.write(self.style.SUCCESS("\n✓ Tier 승격 발생"))
        else:
            self.stdout.write(self.style.WARNING(
                "\n⚠ 승격 미발생\n"
                "  체크 항목:\n"
                "  - 활성 동적 zone 이 있는가? (없으면 trigger_test_zone 먼저)\n"
                "  - 대상 센서가 zone 반경 내인가?\n"
                "  - baseline 데이터가 충분한가? (--with-baseline 옵션 시도)"
            ))
