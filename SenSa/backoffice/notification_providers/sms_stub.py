"""
SmsStubProvider — SMS gateway 자리.

운영 시 Twilio / 알리고 / NHN Cloud 등 어댑터로 교체.
지금은 logger 에 출력만 하고 sent 처리.
"""

import logging

# SMS 발송 시뮬 결과를 로그로 출력하기 위한 모듈.

logger = logging.getLogger(__name__)
# 'backoffice.notification_providers.sms_stub' 로거.


class SmsStubProvider:
    name = "sms_stub"
    # SMS 채널의 스텁(stub) 구현체.
    # 실제 문자 발송 없이 전화번호 유무만 확인하고 성공/실패를 흉내냄.

    def send(self, recipient, message: str, log) -> tuple[bool, str]:
        phone = getattr(recipient, "phone_number", "") or getattr(
            recipient, "phone", ""
        )
        # 수신자 User 모델에서 전화번호를 가져옴.
        # 필드명이 'phone_number'와 'phone' 두 가지 가능성을 모두 처리함.
        if not phone:
            return False, "수신자 전화번호 없음"
            # 전화번호가 없는 사용자는 발송 불가. 'skipped' 처리됨.
        logger.info("[notify:sms_stub] to=%s msg=%s", phone, message[:60])
        # 실제 SMS 대신 로그에 수신 번호와 메시지(최대 60자)를 출력.
        # 운영 환경에서는 이 부분을 Twilio/알리고 API 호출로 교체함.
        return True, ""
        # 스텁이므로 전화번호만 있으면 무조건 성공 처리. 실제 문자 발송 없음.
