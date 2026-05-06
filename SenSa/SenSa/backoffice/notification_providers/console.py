"""
ConsoleProvider — 개발/테스트용. logger 에 출력하고 sent 처리.
"""
import logging

logger = logging.getLogger(__name__)


class ConsoleProvider:
    name = 'console'

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
            '[notify:console] channel=%s recipient=%s msg=%s',
            log.channel, recipient.username if recipient else '-', message[:80],
        )
        return True, ''
