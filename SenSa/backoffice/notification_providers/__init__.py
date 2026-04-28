"""
notification_providers — 채널별 알림 발송 어댑터.

추상 인터페이스: NotificationProvider.send(recipient, message, log) -> tuple[ok, err]

settings.NOTIFICATION_PROVIDERS 로 활성화:
    NOTIFICATION_PROVIDERS = {
        'app':      'backoffice.notification_providers.console.ConsoleProvider',
        'realtime': 'backoffice.notification_providers.console.ConsoleProvider',
        'email':    'backoffice.notification_providers.email.EmailProvider',
        'sms':      'backoffice.notification_providers.sms_stub.SmsStubProvider',
    }

설정에 없는 채널 → console fallback (개발환경 안전).
운영 배포 시 실제 SMTP/FCM 자격증명을 settings 에 주입.
"""
from importlib import import_module
from django.conf import settings


_DEFAULT = 'backoffice.notification_providers.console.ConsoleProvider'


def get_provider(channel: str):
    """채널에 매핑된 Provider 클래스 인스턴스 반환."""
    cfg = getattr(settings, 'NOTIFICATION_PROVIDERS', {}) or {}
    path = cfg.get(channel, _DEFAULT)
    module_path, _, cls_name = path.rpartition('.')
    module = import_module(module_path)
    cls = getattr(module, cls_name)
    return cls()
