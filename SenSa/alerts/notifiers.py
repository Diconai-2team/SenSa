"""
alerts/notifiers.py — 외부 알림 채널 (Slack/Discord webhook).

[Phase I-4]
환경변수로 webhook URL 설정. 없으면 graceful skip.
DRY_RUN 모드: 실제 발송 대신 로그만 — webhook URL 없이도 동작 검증 가능.

[환경변수]
    SLACK_WEBHOOK_URL      Slack incoming webhook URL (없으면 Slack skip)
    DISCORD_WEBHOOK_URL    Discord webhook URL (없으면 Discord skip)
    SENSA_NOTIFY_DRY_RUN   'true' 면 실제 발송 안 하고 로그만 (검증용)

[발송 정책]
- critical 승격 이벤트만 (소음 방지)
- 추후 sensor_danger 등 다른 이벤트 추가 가능

[안전성]
- webhook URL 미설정 → skip (no-op)
- requests 라이브러리 없음 → ImportError graceful 처리
- webhook 응답 5초 timeout → 라이프사이클 지연 방지
- 모든 예외 흡수 → 알림 실패해도 본 로직 영향 없음
"""
import logging
import os


logger = logging.getLogger('alerts.notifiers')


# ── 환경변수 ──
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')
DRY_RUN = os.environ.get('SENSA_NOTIFY_DRY_RUN', 'false').lower() == 'true'


# ── Severity 별 이모지 (메시지 가독성) ──
SEVERITY_EMOJI = {
    'info':     'ℹ️',
    'caution':  '⚠️',
    'danger':   '🚨',
    'critical': '🔴',
}


def is_configured() -> bool:
    """webhook 하나라도 설정됐거나 DRY_RUN 모드인가."""
    return bool(SLACK_WEBHOOK_URL or DISCORD_WEBHOOK_URL or DRY_RUN)


def _post_webhook(url: str, payload: dict, channel: str) -> bool:
    """공통 webhook POST. 성공 시 True.

    [b-1] 발송 실패 시 예외를 삼키지 않고 재전파한다.
        호출 체인: send_external_notification_task → notify_external → 이 함수.
        예외가 task 까지 올라가면 autoretry_for=(Exception,) 가 잡아
        자동 재시도(5s→10s→20s, max 3회)를 수행한다.
        과거엔 여기서 except 로 삼키고 False 를 반환해 task 가 succeeded 로
        처리됐고, 그 결과 webhook 장애가 있어도 재시도가 전혀 동작하지 않았다.
    """
    try:
        import requests
    except ImportError:
        # requests 미설치는 일시 장애가 아닌 환경 문제 → 재시도해도 무의미하므로 skip.
        logger.warning(f"requests 라이브러리 없음 — {channel} skip")
        return False

    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        return True
    except Exception as e:
        # 실패 로그 후 재전파 → task autoretry 가 잡아 재시도.
        logger.warning(f"{channel} 발송 실패 (재시도 트리거): {e}")
        raise


def send_slack(text: str) -> bool:
    """Slack incoming webhook 발송."""
    if not SLACK_WEBHOOK_URL:
        return False
    return _post_webhook(
        SLACK_WEBHOOK_URL,
        {'text': text},
        channel='Slack',
    )


def send_discord(text: str) -> bool:
    """Discord webhook 발송."""
    if not DISCORD_WEBHOOK_URL:
        return False
    return _post_webhook(
        DISCORD_WEBHOOK_URL,
        {'content': text},
        channel='Discord',
    )


def notify_external(title: str, message: str, severity: str = 'critical') -> dict:
    """외부 채널 일괄 발송.

    Args:
        title: 알림 제목 (한 줄)
        message: 본문 (여러 줄 가능)
        severity: 'info'/'caution'/'danger'/'critical'

    Returns:
        {
            'slack':    bool,    # 실제 발송 성공
            'discord':  bool,
            'dry_run':  bool,    # DRY_RUN 모드 여부
            'skipped':  bool,    # 미설정으로 전체 skip
        }
    """
    result = {'slack': False, 'discord': False, 'dry_run': False, 'skipped': False}

    if not is_configured():
        result['skipped'] = True
        logger.debug(f"외부 알림 skip (미설정): {title}")
        return result

    emoji = SEVERITY_EMOJI.get(severity, '🔔')
    text = f"{emoji} **[SenSa] {title}**\n{message}"

    if DRY_RUN:
        result['dry_run'] = True
        logger.info(f"[DRY-RUN] 외부 알림 발송 차단:\n{text}")
        return result

    result['slack'] = send_slack(text)
    result['discord'] = send_discord(text)

    logger.info(
        f"외부 알림 발송: title='{title}' "
        f"slack={result['slack']} discord={result['discord']}"
    )
    return result
