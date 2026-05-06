"""
backoffice/signals.py — 알람 → 알림 발송 자동 트리거.

apps.py 의 ready() 에서 import 하여 활성화됨.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from alerts.models import Alarm

from .notification_dispatcher import dispatch_for_alarm


logger = logging.getLogger(__name__)


@receiver(post_save, sender=Alarm)
def alarm_post_save_handler(sender, instance, created, **kwargs):
    """알람이 새로 생성되면 매칭 정책에 따라 NotificationLog 작성.

    [v6] settings.BACKOFFICE_ASYNC_NOTIFY=True 면 큐로 enqueue (비동기),
         False/미설정이면 동기 dispatch (기존 동작).
    """
    if not created:
        return
    try:
        from django.conf import settings
        if getattr(settings, 'BACKOFFICE_ASYNC_NOTIFY', False):
            from .notification_queue import enqueue_alarm_dispatch
            enqueue_alarm_dispatch(instance.id)
            logger.debug('[backoffice.signals] alarm=%s enqueued for async dispatch', instance.id)
        else:
            n = dispatch_for_alarm(instance)
            if n > 0:
                logger.info('[backoffice.signals] alarm=%s → %d notifications dispatched', instance.id, n)
    except Exception as e:
        logger.exception('[backoffice.signals] alarm dispatch error: %r', e)
