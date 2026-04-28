"""
FcmStubProvider — FCM (앱 푸시) 자리.

운영 시 firebase-admin 으로 교체:
  from firebase_admin import messaging
  messaging.send(messaging.Message(...))
"""
import logging

logger = logging.getLogger(__name__)


class FcmStubProvider:
    name = 'fcm_stub'

    def send(self, recipient, message: str, log) -> tuple[bool, str]:
        token = getattr(recipient, 'fcm_token', '')
        if not token:
            # token 없는 사용자 → skipped 처리 (실패 아님)
            return False, '디바이스 토큰 없음'
        logger.info('[notify:fcm_stub] token=%s... msg=%s', token[:8], message[:60])
        return True, ''
