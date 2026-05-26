"""
alerts/tasks.py — Celery 비동기 task.

[Phase I-4]
외부 알림 발송을 Celery task 로 격리. webhook 응답 지연이 호출 측
(zone 라이프사이클, alarm 생성 핸들러 등) 에 영향 없도록.

호출 측은 .delay() 만 호출하면 즉시 반환, 실제 webhook 발송은 worker 가 처리.

[Phase 2 STEP 8 — 재시도 정책 (P2)]
외부 webhook 은 네트워크 일시 장애 가능 → autoretry + 지수 backoff.
"""
from celery import shared_task

from alerts.notifiers import notify_external


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
) -> dict:
    """외부 알림 발송 (Slack/Discord).

    호출 예시:
        send_external_notification_task.delay(
            title="Zone 긴급 승격",
            message="zone: sensor_01 CO 확산\\ntier: confirmed → critical",
            severity='critical',
        )

    재시도:
        max_retries=3, countdown=5s, exponential backoff

    Returns:
        {'slack': bool, 'discord': bool, 'dry_run': bool, 'skipped': bool}
    """
    return notify_external(title, message, severity)
