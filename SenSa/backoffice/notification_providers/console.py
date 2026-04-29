"""
ConsoleProvider — 개발/테스트용. logger 에 출력하고 sent 처리.
"""

import logging

# 실제 외부 발송 없이 서버 로그에 알림 내용을 출력하는 개발용 Provider.

logger = logging.getLogger(__name__)
# 이 모듈 전용 로거. 출력 채널은 Django 로깅 설정에 따라 결정됨(콘솔, 파일 등).


class ConsoleProvider:
    name = "console"
    # 이 Provider의 식별자. settings.py에서 채널에 매핑할 때 쓰는 이름과는 별개로, 디버깅용.

    def send(self, recipient, message: str, log) -> tuple[bool, str]:
        """
        Args:
            recipient: User 인스턴스
            message: 발송할 메시지 텍스트
            log: NotificationLog 인스턴스 (아직 send_status='pending')
        Returns:
            (ok, error_message) — ok=True 면 발송 성공
        """
        logger.info(
            "[notify:console] channel=%s recipient=%s msg=%s",
            log.channel,
            recipient.username if recipient else "-",
            message[:80],
        )
        # 실제 발송 없이 로그에만 출력. message는 최대 80자까지만 기록.
        # channel(app/email 등), 수신자 username, 메시지를 한 줄로 기록.
        return True, ""
        # 개발 환경에서 항상 성공으로 처리. NotificationLog.send_status가 'sent'로 업데이트됨.
