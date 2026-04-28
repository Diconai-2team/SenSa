"""
python manage.py cleanup_data — 운영 데이터 보관 정책 적용

각 활성 정책에 대해:
  - 기준일(now - retention_days) 이전 데이터 삭제
  - DataRetentionPolicy.last_run_at, last_run_deleted 갱신

cron 등록 권장:
  0 3 * * *  cd /your/SenSa && python manage.py cleanup_data >> /var/log/cleanup.log

운영 시 --dry-run 으로 먼저 확인.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from backoffice.models import DataRetentionPolicy


# target ↔ Model 매핑
def _resolve_qs(target: str, cutoff):
    """target 코드 → 삭제 대상 queryset"""
    if target == 'sensor_data':
        from devices.models import SensorData
        return SensorData.objects.filter(created_at__lt=cutoff) if hasattr(SensorData, 'created_at') else None
    if target == 'worker_location':
        from workers.models import WorkerLocation
        return WorkerLocation.objects.filter(timestamp__lt=cutoff) if hasattr(WorkerLocation, 'timestamp') else None
    if target == 'alarms':
        from alerts.models import Alarm
        return Alarm.objects.filter(created_at__lt=cutoff)
    if target == 'notification_logs':
        from backoffice.models import NotificationLog
        return NotificationLog.objects.filter(created_at__lt=cutoff)
    if target == 'audit_logs':
        return None  # 미구현
    return None


class Command(BaseCommand):
    help = '운영 데이터 보관 정책 (DataRetentionPolicy) 에 따라 누적 데이터를 삭제합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='실제 삭제하지 않고 대상 건수만 출력')
        parser.add_argument('--target', type=str, default='', help='특정 target 만 처리 (예: alarms)')

    def handle(self, *args, **options):
        dry = options['dry_run']
        only_target = options['target'] or None

        qs = DataRetentionPolicy.objects.filter(is_active=True)
        if only_target:
            qs = qs.filter(target=only_target)

        total_deleted = 0
        now = timezone.now()
        for policy in qs:
            cutoff = now - timedelta(days=policy.retention_days)
            target_qs = _resolve_qs(policy.target, cutoff)
            if target_qs is None:
                self.stdout.write(self.style.WARNING(
                    f'  [skip] {policy.target}: 모델 매핑 없음 또는 미구현'
                ))
                continue

            count = target_qs.count()
            if dry:
                self.stdout.write(
                    f'  [dry-run] {policy.target} ({policy.retention_days}일 이전): {count}건 삭제 예정'
                )
                continue

            deleted, _ = target_qs.delete()
            policy.last_run_at = now
            policy.last_run_deleted = deleted
            policy.save(update_fields=['last_run_at', 'last_run_deleted'])
            total_deleted += deleted
            self.stdout.write(self.style.SUCCESS(
                f'  [ok] {policy.target}: {deleted}건 삭제'
            ))

        if dry:
            self.stdout.write('\n--dry-run 모드 — 실제 삭제는 일어나지 않았습니다.')
        else:
            self.stdout.write(self.style.SUCCESS(f'\n총 {total_deleted}건 삭제 완료'))
