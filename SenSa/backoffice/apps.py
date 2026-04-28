from django.apps import AppConfig


class BackofficeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backoffice'
    verbose_name = '백오피스 (관리자 콘솔)'

    def ready(self):
        # 시그널 등록 — alerts.Alarm 생성 시 알림 디스패처 자동 트리거
        from . import signals  # noqa: F401
        # v6 — 감사 로그 자동 기록 시그널
        from . import audit    # noqa: F401
        # v6 — 비동기 알림 워커 (settings.BACKOFFICE_ASYNC_NOTIFY=True 일 때만 기동)
        from .notification_queue import start_worker_if_enabled
        start_worker_if_enabled()
