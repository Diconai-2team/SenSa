"""
EmailProvider — Django send_mail 사용.

settings:
  EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS, DEFAULT_FROM_EMAIL
  → 미설정이면 Django console.EmailBackend (콘솔 출력) 사용.
"""

import logging

# 이메일 발송 실패 시 에러를 기록하기 위한 로깅 모듈.

from django.conf import settings

# DEFAULT_FROM_EMAIL 등 이메일 관련 Django 설정을 가져오는 데 사용.

from django.core.mail import send_mail

# Django 기본 이메일 발송 함수. settings의 EMAIL_BACKEND에 따라 실제 SMTP 또는 콘솔 출력.

logger = logging.getLogger(__name__)
# 'backoffice.notification_providers.email' 로거. 발송 실패 로그 기록에 사용.


class EmailProvider:
    name = "email"
    # 이 Provider가 처리하는 채널 이름.

    def send(self, recipient, message: str, log) -> tuple[bool, str]:
        if not recipient or not getattr(recipient, "email", ""):
            return False, "수신자 이메일 없음"
            # 수신자가 없거나 이메일 주소가 비어있으면 발송 불가. 실패가 아닌 'skipped' 처리됨.
        try:
            send_mail(
                subject="[SenSa] 알림",
                # 이메일 제목. 운영 환경에서는 알람 종류에 따라 동적으로 변경하는 것이 좋음.
                message=message,
                # 이메일 본문. notification_dispatcher에서 정책 템플릿을 렌더링한 텍스트.
                from_email=getattr(
                    settings, "DEFAULT_FROM_EMAIL", "noreply@sensa.local"
                ),
                # 발신자 주소. settings에 없으면 기본값 사용.
                recipient_list=[recipient.email],
                # 수신자 이메일 목록. 항상 1명씩 발송(1 사용자 × 1 채널 = 1 NotificationLog 원칙).
                fail_silently=False,
                # True로 하면 SMTP 에러를 무시함. False여야 아래 except에서 잡을 수 있음.
            )
            return True, ""
            # 발송 성공. NotificationLog.send_status → 'sent'로 업데이트됨.
        except Exception as e:
            logger.warning("[notify:email] send failed: %r", e)
            return False, str(e)[:300]
            # SMTP 연결 실패, 인증 오류 등 예외 발생 시 실패 반환.
            # error_message를 300자로 잘라서 NotificationLog.error_message에 저장됨.
