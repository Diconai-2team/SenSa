"""
backoffice/tasks.py — 데이터 보관 정책 + 주기적 유지보수 Celery 태스크

Celery Beat 에서 자동 실행:
  settings.CELERY_BEAT_SCHEDULE['cleanup-retention-data']   (매일)
    → backoffice.tasks.run_cleanup
  settings.CELERY_BEAT_SCHEDULE['cleanup-expired-ai-predictions']  (5분마다)
    → backoffice.tasks.cleanup_expired_ai_predictions
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='backoffice.tasks.cleanup_expired_ai_predictions')
def cleanup_expired_ai_predictions():
    """만료된 AIPrediction pending → failure 자동 처리.

    ARIMA 예측 알람 생성 시 AIPrediction(result='pending', expires_at=now+30s) 저장.
    실측값이 30초 안에 threshold를 넘으면 devices/views._verify_ai_predictions()가
    result='success'로 갱신하지만, 다음 두 경우 pending이 방치됨:
      1. spike 태스크처럼 REST API를 우회해 DB 직접 저장한 경우
         → _verify_ai_predictions() 미호출 → expires_at 지나도 pending 유지
      2. 서버 재시작 / 데이터 공백으로 검증 틱 자체가 오지 않은 경우

    이 태스크가 5분마다 만료된 pending을 failure로 정리하여
    arima_accuracy 지표가 올바르게 집계되도록 보장.

    Returns:
        {'marked_failure': int}  — failure로 전환된 건수
    """
    from alerts.models import AIPrediction

    now = timezone.now()
    expired_qs = AIPrediction.objects.filter(
        result='pending',
        expires_at__lt=now,
    )
    count = expired_qs.count()
    if count:
        expired_qs.update(result='failure')
        logger.info('[ai_pred_cleanup] 만료 pending %d건 → failure 처리', count)
    else:
        logger.debug('[ai_pred_cleanup] 만료 pending 없음')

    return {'marked_failure': count}


@shared_task(name='backoffice.tasks.run_cleanup', bind=True, max_retries=2)
def run_cleanup(self):
    """DataRetentionPolicy 에 등록된 활성 정책을 순회하며 오래된 데이터 삭제."""
    from backoffice.models import DataRetentionPolicy
    from backoffice.management.commands.cleanup_data import _resolve_qs

    now = timezone.now()
    total_deleted = 0

    for policy in DataRetentionPolicy.objects.filter(is_active=True):
        try:
            cutoff = now - timedelta(days=policy.retention_days)
            qs = _resolve_qs(policy.target, cutoff)
            if qs is None:
                logger.debug("[cleanup] %s: 매핑 없음, 스킵", policy.target)
                continue

            deleted, _ = qs.delete()
            policy.last_run_at = now
            policy.last_run_deleted = deleted
            policy.save(update_fields=['last_run_at', 'last_run_deleted'])
            total_deleted += deleted
            logger.info("[cleanup] %s: %d건 삭제 (보관 %d일)", policy.target, deleted, policy.retention_days)

        except Exception as exc:
            logger.warning("[cleanup] %s 처리 중 오류: %s", policy.target, exc)

    logger.info("[cleanup] 완료 — 총 %d건 삭제", total_deleted)
    return {'total_deleted': total_deleted}
