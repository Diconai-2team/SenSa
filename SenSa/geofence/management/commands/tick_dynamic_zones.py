"""
관리 명령: 동적 zone 시간 진행 (반경 + 만료 + 승격 통합).

사용:
    python manage.py tick_dynamic_zones
    python manage.py tick_dynamic_zones --no-upgrade-check
    python manage.py tick_dynamic_zones --quiet
"""
from django.core.management.base import BaseCommand
from geofence.zone_lifecycle import tick


class Command(BaseCommand):
    help = '동적 zone 의 반경 진화 + 만료 처리 + tier 승격 검사 (한 사이클)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='출력 최소화 (cron 등록 시 유용)',
        )
        parser.add_argument(
            '--no-upgrade-check',
            action='store_true',
            help='tier 승격 검사 skip (반경/만료만 처리)',
        )

    def handle(self, *args, **options):
        result = tick(check_upgrade=not options['no_upgrade_check'])

        if not options['quiet']:
            msg = (
                f"tick 완료 — "
                f"갱신: {result['updated']}, "
                f"만료: {result['expired']}, "
                f"확인 승격: {result['upgraded_to_confirmed']}, "
                f"긴급 승격: {result['upgraded_to_critical']}"
            )
            self.stdout.write(msg)
