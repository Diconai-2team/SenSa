"""
alerts/tasks.py — Celery 비동기 task.

[Phase I-4]
외부 알림 발송을 Celery task 로 격리. webhook 응답 지연이 호출 측
(zone 라이프사이클, alarm 생성 핸들러 등) 에 영향 없도록.

호출 측은 .delay() 만 호출하면 즉시 반환, 실제 webhook 발송은 worker 가 처리.

[Phase 2 STEP 8 — 재시도 정책 (P2)]
외부 webhook 은 네트워크 일시 장애 가능 → autoretry + 지수 backoff.

[알림 발송 이력 연동]
send_external_notification_task 실행 결과(성공/실패)를 NotificationLog 에 기록.
  - alarm_id 가 있으면 Alarm FK 연결
  - 채널별(slack/discord) 각 1건
  - send_status: 'sent' / 'failed' / 'skipped'
"""
import logging

from django.utils import timezone
from celery import shared_task

from alerts.notifiers import notify_external

logger = logging.getLogger(__name__)


@shared_task(
    name='alerts.tasks.send_external_notification',
    # [P2 STEP 8] 재시도 정책 — 네트워크 일시 장애 대비
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 5},
    retry_backoff=True,     # 5s → 10s → 20s 지수 backoff
    retry_jitter=True,      # 동시 재시도 충돌 방지
)
def send_external_notification_task(
    title: str,
    message: str,
    severity: str = 'critical',
    alarm_id: int | None = None,
) -> dict:
    """외부 알림 발송 (Slack/Discord) + NotificationLog 이력 저장.

    호출 예시:
        send_external_notification_task.delay(
            title="Zone 긴급 승격",
            message="zone: sensor_01 CO 확산\\ntier: confirmed → critical",
            severity='critical',
            alarm_id=alarm.id,   # 연결할 Alarm PK (선택)
        )

    재시도:
        max_retries=3, countdown=5s, exponential backoff

    NotificationLog:
        slack / discord 채널 각 1건 기록.
        send_status: 'sent' (성공) | 'failed' (실패) | 'skipped' (미설정)

    Returns:
        {'slack': bool, 'discord': bool, 'dry_run': bool, 'skipped': bool}
    """
    result = notify_external(title, message, severity)
    _save_notification_log(result, alarm_id, title, message)
    return result


def _save_notification_log(
    result: dict,
    alarm_id: int | None,
    title: str,
    message: str,
) -> None:
    """발송 결과를 NotificationLog 에 채널별로 기록.

    실패해도 메인 task 결과에 영향 없도록 모든 예외 흡수.
    """
    try:
        from django.db import close_old_connections
        close_old_connections()

        from backoffice.models import NotificationLog

        # DRY_RUN 또는 완전 skip 이면 skipped 로 1건만 기록
        if result.get('skipped'):
            _write_log(NotificationLog, alarm_id, 'slack',   'skipped', title)
            return
        if result.get('dry_run'):
            _write_log(NotificationLog, alarm_id, 'slack',   'skipped', title, '(DRY_RUN)')
            _write_log(NotificationLog, alarm_id, 'discord', 'skipped', title, '(DRY_RUN)')
            return

        # 실제 발송 결과 기록
        now = timezone.now()

        slack_ok = result.get('slack', False)
        _write_log(
            NotificationLog, alarm_id, 'slack',
            'sent' if slack_ok else 'failed',
            title,
            sent_at=now if slack_ok else None,
        )

        discord_ok = result.get('discord', False)
        _write_log(
            NotificationLog, alarm_id, 'discord',
            'sent' if discord_ok else 'failed',
            title,
            sent_at=now if discord_ok else None,
        )

    except Exception as exc:
        logger.warning('[notify_log] NotificationLog 저장 실패 — 무시: %s', exc)


def _write_log(
    NotificationLog,
    alarm_id: int | None,
    channel: str,
    send_status: str,
    title: str,
    error_message: str = '',
    sent_at=None,
) -> None:
    """NotificationLog 1건 기록."""
    alarm = None
    if alarm_id:
        try:
            from alerts.models import Alarm
            alarm = Alarm.objects.get(pk=alarm_id)
        except Exception:
            pass  # Alarm 조회 실패 시 FK 없이 기록

    NotificationLog.objects.create(
        policy=None,                              # 정책 기반 아닌 이벤트 직접 발송
        alarm=alarm,
        recipient=None,                           # 특정 수신자 없음 (채널 발송)
        recipient_name_snapshot=f'[{channel.upper()}] {title[:60]}',
        channel=channel,
        send_status=send_status,
        error_message=error_message,
        sent_at=sent_at,
    )
