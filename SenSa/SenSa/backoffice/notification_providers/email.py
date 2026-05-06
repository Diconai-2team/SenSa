"""
EmailProvider — Django send_mail 사용.

settings:
  EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS, DEFAULT_FROM_EMAIL
  → 미설정이면 Django console.EmailBackend (콘솔 출력) 사용.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


class EmailProvider:
    name = 'email'

    def send(self, recipient, message: str, log) -> tuple[bool, str]:
        if not recipient or not getattr(recipient, 'email', ''):
            return False, '수신자 이메일 없음'
        try:
            send_mail(
                subject='[SenSa] 알림',
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@sensa.local'),
                recipient_list=[recipient.email],
                fail_silently=False,
            )
            return True, ''
        except Exception as e:
            logger.warning('[notify:email] send failed: %r', e)
            return False, str(e)[:300]
