"""
backoffice/signals.py — 알람 → 알림 발송 자동 트리거.

apps.py 의 ready() 에서 import 하여 활성화됨.
"""

import logging

# Python 표준 로깅 모듈. 이 파일에서 발생하는 디버그/에러 메시지를 기록하는 데 사용.

from django.db.models.signals import post_save

# Django 시그널 시스템. 모델 저장(INSERT/UPDATE) 이후 자동으로 연결된 함수를 호출해 줌.

from django.dispatch import receiver

# @receiver 데코레이터. 특정 시그널과 함수를 연결해서 시그널 발생 시 자동 실행되게 만들어 줌.

from alerts.models import Alarm

# 알람 이벤트 모델. 이 파일에서는 "알람이 새로 저장될 때"를 감지하기 위해 참조.

from .notification_dispatcher import dispatch_for_alarm

# 알람에 매칭되는 알림 정책을 찾아서 NotificationLog를 생성하고 실제 발송하는 핵심 함수.


logger = logging.getLogger(__name__)
# 이 모듈 전용 로거 생성. 로그 출력 시 'backoffice.signals'라는 이름으로 구분됨.


@receiver(post_save, sender=Alarm)
# Alarm 모델이 저장될 때(INSERT 또는 UPDATE) 이 함수가 자동으로 호출됨.
def alarm_post_save_handler(sender, instance, created, **kwargs):
    """알람이 새로 생성되면 매칭 정책에 따라 NotificationLog 작성.

    [v6] settings.BACKOFFICE_ASYNC_NOTIFY=True 면 큐로 enqueue (비동기),
         False/미설정이면 동기 dispatch (기존 동작).
    """
    if not created:
        return
        # UPDATE(수정)인 경우에는 아무것도 하지 않음. 알림은 최초 생성 시에만 발송.

    try:
        from django.conf import settings

        if getattr(settings, "BACKOFFICE_ASYNC_NOTIFY", False):
            # 비동기 모드: 알람 ID만 큐에 넣고 즉시 리턴. 워커 스레드가 백그라운드에서 처리.
            from .notification_queue import enqueue_alarm_dispatch

            enqueue_alarm_dispatch(instance.id)
            logger.debug(
                "[backoffice.signals] alarm=%s enqueued for async dispatch", instance.id
            )
        else:
            # 동기 모드: 지금 바로 정책 매칭·발송 처리. 요청 흐름 안에서 완료됨.
            n = dispatch_for_alarm(instance)
            if n > 0:
                logger.info(
                    "[backoffice.signals] alarm=%s → %d notifications dispatched",
                    instance.id,
                    n,
                )
    except Exception as e:
        logger.exception("[backoffice.signals] alarm dispatch error: %r", e)
        # 알림 발송 실패가 알람 저장 자체를 롤백시키지 않도록 예외를 삼킴.
        # 로그에는 남기므로 운영 중 디버깅 가능.
