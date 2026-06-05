"""
backoffice/tasks.py — 운영 데이터 보관 정책 자동 적용.

`cleanup_data` 관리 명령(DataRetentionPolicy 기반 보존기간 초과분 삭제)을
Celery 태스크로 감싸 beat 스케줄(기본 매일 03:00)에서 호출한다.

cron 대신 Celery beat 를 쓰는 이유:
  - K8s 에는 호스트 cron 이 없고, celery worker(-B) 가 이미 beat 를 돌리고 있어
    별도 CronJob 없이 단일 출처로 주기 실행 가능.
  - 태스크 실행/실패가 sensa_celery_task_total 메트릭에 자동 기록되어 관측됨.
"""
import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(name='backoffice.tasks.run_cleanup_data', ignore_result=True)
def run_cleanup_data() -> str:
    """보관 정책 초과 데이터 삭제. 실패해도 beat 다음 주기에 재시도되므로 raise 안 함."""
    try:
        call_command('cleanup_data')
        logger.info('[cleanup_data] 보관 정책 적용 완료')
        return 'ok'
    except Exception as exc:                      # noqa: BLE001
        logger.exception('[cleanup_data] 실패: %s', exc)
        return f'error: {exc}'


# ──────────────────────────────────────────────────────────────
# 운영 데이터 백업/초기화 오프로드 (v7 → async)
#   웹 요청 안에서 66만+ 행을 백업·삭제하면 daphne 워커가 오래 묶여
#   /metrics readiness probe(3s)가 실패 → K8s 가 그 Pod 을 재시작 → 통로 끊김.
#   그래서 무거운 작업은 Celery 워커로 옮기고, 웹은 enqueue 후 즉시 202 반환.
# ──────────────────────────────────────────────────────────────
def _audit_async(action, target, filename, count,
                 actor_id=None, actor_username='', ip='', path=''):
    """request 없이 감사 로그 기록 (Celery 태스크용). 실패해도 본작업 안 끊음."""
    try:
        from django.contrib.auth import get_user_model
        from .models import AuditLog
        User = get_user_model()
        actor = User.objects.filter(pk=actor_id).first() if actor_id else None
        AuditLog.objects.create(
            actor=actor,
            actor_username_snapshot=actor_username or (getattr(actor, 'username', '') or ''),
            action=action,
            target_app='backoffice',
            target_model='DataRetentionPolicy',
            target_pk=None,
            target_repr=f'{target} ({filename or "-"})',
            changes={'target': target, 'filename': filename, 'count': count},
            ip_address=ip or '',
            request_path=path or '',
            extra_message=f'운영 데이터 {action}: {target} (async)',
        )
    except Exception as e:                          # noqa: BLE001
        logger.warning('[backoffice audit-async] 기록 실패: %s', e)


@shared_task(name='backoffice.tasks.run_backup', ignore_result=True)
def run_backup(target, actor_id=None, actor_username='', ip='', path='') -> dict:
    """단건 정책 데이터를 .json.gz 로 스트리밍 백업 (워커에서)."""
    from backoffice.utils import backup as backup_util
    result = backup_util.stream_backup_to_file(target)
    backup_util.cleanup_old_backups(target)
    _audit_async('data_backup', target, result['filename'], result['count'],
                 actor_id, actor_username, ip, path)
    logger.info('[run_backup] %s — %s건 백업', target, result['count'])
    return {'filename': result['filename'], 'count': result['count']}


@shared_task(name='backoffice.tasks.run_init_with_backup', ignore_result=True)
def run_init_with_backup(target, actor_id=None, actor_username='', ip='', path='') -> dict:
    """단건 정책 데이터를 백업 후 청크 삭제 (워커에서). 백업 성공해야 삭제 진행."""
    from backoffice.utils import backup as backup_util
    # 1) 백업
    result = backup_util.stream_backup_to_file(target)
    backup_util.cleanup_old_backups(target)
    _audit_async('data_backup_pre_init', target, result['filename'], result['count'],
                 actor_id, actor_username, ip, path)
    # 2) 청크 삭제
    deleted = backup_util.delete_all_data(target)
    _audit_async('data_init', target, result['filename'], deleted,
                 actor_id, actor_username, ip, path)
    logger.info('[run_init_with_backup] %s — 백업 %s건 → 삭제 %s건',
                target, result['count'], deleted)
    return {'filename': result['filename'], 'backed_up': result['count'], 'deleted': deleted}
