"""
SmsStubProvider — SMS gateway 자리.

운영 시 Twilio / 알리고 / NHN Cloud 등 어댑터로 교체.
지금은 logger 에 출력만 하고 sent 처리.
"""
import logging

logger = logging.getLogger(__name__)


class SmsStubProvider:
    name = 'sms_stub'

    def send(self, recipient, message: str, log) -> tuple[bool, str]:
        phone = getattr(recipient, 'phone_number', '') or getattr(recipient, 'phone', '')
        if not phone:
            return False, '수신자 전화번호 없음'
        logger.info('[notify:sms_stub] to=%s msg=%s', phone, message[:60])
        return True, ''
