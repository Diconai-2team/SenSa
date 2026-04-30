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

# Python 3.10 미만에서도 타입힌트에 '|' 구문을 쓸 수 있도록 허용하는 future import.

import logging
import queue

# Python 내장 스레드 안전 큐. 여러 스레드에서 동시에 put/get 해도 안전함.

import threading

# Python 내장 스레드 라이브러리. 워커 스레드를 만들고 실행하는 데 사용.

logger = logging.getLogger(__name__)
# 이 모듈 전용 로거. 로그 메시지는 'backoffice.notification_queue'로 식별됨.


class _NotificationWorker:
    """싱글톤. 한 프로세스에 워커 1개."""

    # 이 클래스 인스턴스가 전체 Django 프로세스에 딱 1개만 존재하도록 싱글톤 패턴 사용.
    # 여러 곳에서 enqueue_alarm_dispatch를 호출해도 같은 큐에 쌓임.
    _instance = None

    def __init__(self):
        self.queue: queue.Queue = queue.Queue()
        # 발송할 알람 작업을 담는 무제한 크기의 스레드 안전 큐.
        self.thread: threading.Thread | None = None
        # 실제로 큐를 소비하며 발송 처리를 수행하는 데몬 스레드.
        self.running = False
        # 워커 루프를 계속 실행할지 여부를 제어하는 플래그.

    @classmethod
    def get(cls):
        # 클래스 레벨의 인스턴스를 반환. 없으면 최초 1회 생성.
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self):
        # 워커 스레드를 시작. 이미 실행 중이면 중복 시작 방지.
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(
            target=self._loop,
            name="notification-worker",
            daemon=True,
            # daemon=True: 메인 프로세스가 종료되면 이 스레드도 자동으로 종료됨.
            # (사용자가 서버를 끄면 대기 중인 알림은 손실될 수 있음 — Celery 필요 시점)
        )
        self.thread.start()
        logger.info("[notify_queue] worker started")

    def _loop(self):
        # 워커 스레드의 메인 루프. 큐에서 작업을 꺼내 처리하고, 비어 있으면 1초 대기.
        from .notification_dispatcher import dispatch_for_alarm

        # 순환 import 방지를 위해 함수 안에서 import.
        from alerts.models import Alarm

        while self.running:
            try:
                item = self.queue.get(timeout=1.0)
                # 큐에서 작업 하나를 꺼냄. 1초 동안 작업이 없으면 Empty 예외 발생.
            except queue.Empty:
                continue
                # 큐가 비었으면 다시 루프를 돌며 대기.
            try:
                kind, payload = item
                if kind == "alarm":
                    alarm_id = payload
                    try:
                        alarm = Alarm.objects.get(id=alarm_id)
                        # 알람 ID로 DB에서 실제 알람 객체를 가져옴.
                    except Alarm.DoesNotExist:
                        continue
                        # 알람이 이미 삭제된 경우 조용히 건너뜀.
                    dispatch_for_alarm(alarm)
                    # 실제 알림 발송 처리: 정책 매칭 → 수신자 확인 → NotificationLog 기록.
            except Exception as e:
                logger.exception("[notify_queue] task failed: %r", e)
                # 발송 중 예외가 나도 워커 루프는 계속 돌아야 하므로 예외를 잡아서 로그만 남김.
            finally:
                self.queue.task_done()
                # 큐에 이 작업이 완료됐음을 알림. queue.join()을 쓸 경우 필요.

    def enqueue(self, kind: str, payload):
        # 작업을 큐에 넣음. 메인 스레드(요청 처리 흐름)에서 호출하며, 워커가 비동기로 처리.
        self.queue.put((kind, payload))


def enqueue_alarm_dispatch(alarm_id: int):
    """알람 ID 를 큐에 넣음. 워커가 비동기로 처리.

    settings.BACKOFFICE_ASYNC_NOTIFY=False 면 워커 미기동이라 enqueue 도 무의미 →
    이 헬퍼 호출 측에서 settings 토글 검사 후 분기.
    """
    _NotificationWorker.get().enqueue("alarm", alarm_id)
    # 싱글톤 워커 인스턴스의 큐에 ('alarm', alarm_id) 튜플을 넣음.
    # 워커 스레드가 루프에서 꺼내 dispatch_for_alarm(alarm)을 호출할 것임.


def start_worker_if_enabled():
    """apps.ready() 에서 호출 — settings 보고 활성화."""
    # Django 앱 초기화 시점(apps.py의 ready())에 호출됨.
    # 비동기 알림 설정이 켜져 있을 때만 워커 스레드를 기동함.
    from django.conf import settings

    if not getattr(settings, "BACKOFFICE_ASYNC_NOTIFY", False):
        return
        # BACKOFFICE_ASYNC_NOTIFY=False(기본값)이면 워커를 띄우지 않음.
        # 개발 환경에서는 동기 처리가 더 디버깅하기 쉬우므로 의도적인 설계.
    _NotificationWorker.get().start()
    # 설정이 True이면 워커 스레드를 시작. 이후 알람 생성 시 큐에 쌓이고 백그라운드에서 발송됨.
