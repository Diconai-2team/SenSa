"""
backoffice/notification_queue.py — 알림 발송 비동기 큐.

Celery 없이 동작하는 daemon thread + queue.Queue 기반 워커.

설계:
  - settings.BACKOFFICE_ASYNC_NOTIFY=True 일 때만 활성화 (개발 환경 동기 유지)
  - 워커 1개 스레드 — 직렬 처리 (NotificationLog DB 쓰기만 하므로 충분)
  - 큐 사이즈 무제한. shutdown 시 in-flight 작업은 손실될 수 있음 (Celery 가 필요한 시점이 그때)
  - apps.ready() 에서 워커 자동 기동

사용:
  from .notification_queue import enqueue_alarm_dispatch
  enqueue_alarm_dispatch(alarm.id)
"""
from __future__ import annotations

import logging
import queue
import threading

logger = logging.getLogger(__name__)


class _NotificationWorker:
    """싱글톤. 한 프로세스에 워커 1개."""
    _instance = None

    def __init__(self):
        self.queue: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.running = False

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(
            target=self._loop, name='notification-worker', daemon=True,
        )
        self.thread.start()
        logger.info('[notify_queue] worker started')

    def _loop(self):
        from .notification_dispatcher import dispatch_for_alarm
        from alerts.models import Alarm

        while self.running:
            try:
                item = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                kind, payload = item
                if kind == 'alarm':
                    alarm_id = payload
                    try:
                        alarm = Alarm.objects.get(id=alarm_id)
                    except Alarm.DoesNotExist:
                        continue
                    dispatch_for_alarm(alarm)
            except Exception as e:
                logger.exception('[notify_queue] task failed: %r', e)
            finally:
                self.queue.task_done()

    def enqueue(self, kind: str, payload):
        self.queue.put((kind, payload))


def enqueue_alarm_dispatch(alarm_id: int):
    """알람 ID 를 큐에 넣음. 워커가 비동기로 처리.

    settings.BACKOFFICE_ASYNC_NOTIFY=False 면 워커 미기동이라 enqueue 도 무의미 →
    이 헬퍼 호출 측에서 settings 토글 검사 후 분기.
    """
    _NotificationWorker.get().enqueue('alarm', alarm_id)


def start_worker_if_enabled():
    """apps.ready() 에서 호출 — settings 보고 활성화."""
    from django.conf import settings
    if not getattr(settings, 'BACKOFFICE_ASYNC_NOTIFY', False):
        return
    _NotificationWorker.get().start()
