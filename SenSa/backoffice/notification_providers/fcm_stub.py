"""
FcmStubProvider — FCM (앱 푸시) 자리.

운영 시 firebase-admin 으로 교체:
  from firebase_admin import messaging
  messaging.send(messaging.Message(...))
"""

import logging

# FCM 발송 시뮬 결과를 로그로 출력하기 위한 모듈.

logger = logging.getLogger(__name__)
# 'backoffice.notification_providers.fcm_stub' 로거.


class FcmStubProvider:
    name = "fcm_stub"
    # FCM 앱 푸시 채널의 스텁(stub) 구현체.
    # 실제 Firebase 연동 없이 토큰 유무만 확인하고 성공/실패를 흉내냄.

    def send(self, recipient, message: str, log) -> tuple[bool, str]:
        token = getattr(recipient, "fcm_token", "")
        # 수신자 User 객체에서 FCM 디바이스 토큰을 가져옴.
        # fcm_token 필드가 없거나 비어있으면 빈 문자열.
        if not token:
            # token 없는 사용자 → skipped 처리 (실패 아님)
            return False, "디바이스 토큰 없음"
            # 토큰 없는 사용자는 앱 미설치로 간주. 발송 실패(failed)가 아닌 건너뜀(skipped) 처리됨.
            # dispatcher에서 err가 있으면 failed, 없으면 skipped로 구분함.
        logger.info("[notify:fcm_stub] token=%s... msg=%s", token[:8], message[:60])
        # 토큰 앞 8자리만 로그에 기록(보안). 실제 환경에서는 Firebase SDK로 메시지 전송.
        return True, ""
        # 스텁이므로 토큰만 있으면 무조건 성공 처리. 실제 전송 없음.
