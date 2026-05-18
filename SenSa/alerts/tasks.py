"""
alerts/tasks.py — Celery 비동기 task.

[Phase I-4]
외부 알림 발송을 Celery task 로 격리. webhook 응답 지연이 호출 측
(zone 라이프사이클, alarm 생성 핸들러 등) 에 영향 없도록.

호출 측은 .delay() 만 호출하면 즉시 반환, 실제 webhook 발송은 worker 가 처리.
"""
from celery import shared_task

from alerts.notifiers import notify_external


@shared_task(name='alerts.tasks.send_external_notification')
def send_external_notification_task(
    title: str,
    message: str,
    severity: str = 'critical',
) -> dict:
    """외부 알림 발송 (Slack/Discord).

    호출 예시:
        send_external_notification_task.delay(
            title="Zone 긴급 승격",
            message="zone: sensor_01 CO 확산\\ntier: confirmed → critical",
            severity='critical',
        )

    Returns:
        {'slack': bool, 'discord': bool, 'dry_run': bool, 'skipped': bool}
    """
    return notify_external(title, message, severity)
