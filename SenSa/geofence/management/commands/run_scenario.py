"""
관리 명령: Phase D 시나리오 실행.

사용:
    # 등록된 시나리오 목록
    python manage.py run_scenario --list

    # 실행 (자동 cleanup)
    python manage.py run_scenario --name single_leak

    # 실행 + 기대 결과 자동 검증 (CI/회귀용)
    python manage.py run_scenario --name single_leak --verify

    # 실행 + cleanup 생략 (DB 에 남김, 디버깅용)
    python manage.py run_scenario --name single_leak --keep
"""
from django.core.management.base import BaseCommand, CommandError

from geofence.scenarios import get_scenario, list_scenarios


class Command(BaseCommand):
    help = 'Phase D — R&D 회귀 시나리오 실행 (인공 device + cleanup 격리)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name', type=str,
            help='시나리오 이름 (또는 --list 로 목록 확인)',
        )
        parser.add_argument(
            '--list', action='store_true',
            help='사용 가능 시나리오 목록 출력',
        )
        parser.add_argument(
            '--verify', action='store_true',
            help='기대 결과 자동 검증 (실패 시 차이점 출력)',
        )
        parser.add_argument(
            '--keep', action='store_true',
            help='cleanup 생략 — 생성된 zone/device DB에 남김 (디버깅)',
        )

    def handle(self, *args, **opts):
        # ── 목록 ──
        if opts['list']:
            self.stdout.write("\n[사용 가능 시나리오]")
            for s in list_scenarios():
                self.stdout.write(f"  - {s['name']}")
                self.stdout.write(f"      {s['description']}")
            self.stdout.write("")
            return

        name = opts.get('name')
        if not name:
            raise CommandError("--name 필수 (또는 --list)")

        # ── 시나리오 로드 ──
        try:
            scenario_cls = get_scenario(name)
        except KeyError as e:
            raise CommandError(str(e))

        self.stdout.write(f"\n{'═' * 60}")
        self.stdout.write(f"  시나리오: {name}")
        self.stdout.write(f"  설명:    {scenario_cls.description}")
        self.stdout.write(f"{'═' * 60}")

        # ── 실행 ──
        scenario = scenario_cls()
        try:
            result = scenario.execute(
                verify=opts['verify'],
                keep=opts['keep'],
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"\n✗ 실행 실패: {type(e).__name__}: {e}"
            ))
            raise

        # ── 출력 ──
        self.stdout.write(f"\n[실행 상태]")
        self.stdout.write(f"  status:      {result['status']}")
        self.stdout.write(f"  cleaned_up:  {result.get('cleaned_up')}")

        if 'actual' in result:
            self.stdout.write(f"\n[실제 결과]")
            for k, v in result['actual'].items():
                self.stdout.write(f"  {k:18s}: {v}")

        if 'expected' in result:
            self.stdout.write(f"\n[기대 결과]")
            for k, v in result['expected'].items():
                self.stdout.write(f"  {k:18s}: {v}")

        if opts['verify']:
            if result.get('verify_ok'):
                self.stdout.write(self.style.SUCCESS(
                    f"\n✓ 검증 통과"
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"\n✗ 검증 실패"
                ))
                for d in result.get('verify_diffs', []):
                    self.stdout.write(self.style.ERROR(f"    - {d}"))

        if result.get('kept_zone_ids'):
            self.stdout.write(self.style.WARNING(
                f"\n⚠ cleanup 생략됨"
                f"\n  남은 zone IDs:   {result['kept_zone_ids']}"
                f"\n  남은 device IDs: {result.get('kept_device_ids', [])}"
                f"\n  수동 정리 예시:"
                f"\n    from geofence.models import GeoFence"
                f"\n    GeoFence.objects.filter(id__in={result['kept_zone_ids']}).delete()"
            ))

        self.stdout.write("")
