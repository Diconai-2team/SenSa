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

# Python 내장 동적 import 함수. 문자열로 된 모듈 경로를 실행 시점에 불러올 때 사용.
# 예: 'backoffice.notification_providers.email' → EmailProvider 클래스를 동적으로 로드.

from django.conf import settings

# Django 설정 파일(settings.py)에 접근하는 인터페이스.
# NOTIFICATION_PROVIDERS 키를 읽어서 어떤 채널에 어떤 Provider를 쓸지 결정.


_DEFAULT = "backoffice.notification_providers.console.ConsoleProvider"
# settings에 채널이 등록되지 않았을 때 사용할 기본 Provider.
# ConsoleProvider는 실제 발송 없이 로그에만 출력하므로, 개발 환경에서 안전하게 fallback됨.


def get_provider(channel: str):
    """채널에 매핑된 Provider 클래스 인스턴스 반환."""
    cfg = getattr(settings, "NOTIFICATION_PROVIDERS", {}) or {}
    # settings.NOTIFICATION_PROVIDERS 딕셔너리를 가져옴. 없으면 빈 딕셔너리.

    path = cfg.get(channel, _DEFAULT)
    # 채널(app/email/sms/realtime)에 해당하는 Provider 클래스 경로 문자열을 가져옴.
    # 등록되지 않은 채널이면 _DEFAULT(ConsoleProvider) 사용.

    module_path, _, cls_name = path.rpartition(".")
    # 'backoffice.notification_providers.email.EmailProvider'를
    # 'backoffice.notification_providers.email' + 'EmailProvider' 로 분리.

    module = import_module(module_path)
    # 모듈 경로 문자열로 실제 Python 모듈을 동적으로 불러옴.

    cls = getattr(module, cls_name)
    # 모듈에서 클래스 이름으로 클래스 객체를 가져옴.

    return cls()
    # Provider 클래스를 인스턴스화해서 반환. 호출하는 쪽에서 .send()를 바로 쓸 수 있음.
