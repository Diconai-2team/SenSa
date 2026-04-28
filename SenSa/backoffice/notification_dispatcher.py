"""
backoffice/notification_dispatcher.py — 알림 발송 디스패처

Celery 없이 동작하는 가벼운 알림 발송 워커.

설계:
  - alerts.Alarm 의 post_save 시그널 → dispatch_for_alarm(alarm) 호출
  - 매칭되는 NotificationPolicy 조회 (risk_category 매핑 + alarm_level priority 이상)
  - 각 정책의 recipients_csv 토큰을 풀어서 실제 사용자 목록 도출
  - 각 (사용자 × 채널) 조합당 NotificationLog 1건 작성
  - 실제 송신은 stub — log 만 작성. v6 에서 SMS gateway / FCM / SMTP 연결.

  → DB 쓰기만 하므로 트랜잭션 안에서 처리해도 무리 없음. 비동기 스레드 미사용.
    (운영에서 알람 발생률이 매우 높으면 scheduler.run_simulation_loop 처럼
     별도 큐로 분리할 수 있음 — 현재 구조에서 그건 v6.)
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone


logger = logging.getLogger(__name__)
User = get_user_model()


# alerts.alarm_level('info'/'caution'/'danger'/'critical') ↔ AlarmLevel.code 매핑
# alerts 의 'info' 는 백오피스에 정의된 게 없으므로 정책 매칭 우선순위 NORMAL 로 매핑.
ALARM_LEVEL_TO_CODE = {
    'info':     'NORMAL',
    'caution':  'CAUTION',
    'danger':   'DANGER',
    'critical': 'DANGER',
}

# alerts.alarm_type ↔ RiskCategory.code 매핑 (휴리스틱)
# alerts.Alarm 의 alarm_type:
#   geofence_enter / sensor_caution / sensor_danger / combined
# RiskCategory.code: RISK_GAS / RISK_POWER / RISK_LOCATION / RISK_WORK / ...
ALARM_TYPE_TO_RISK_CODE_FALLBACK = {
    'geofence_enter': 'RISK_LOCATION',
    'sensor_caution': 'RISK_GAS',     # 센서 = 가스 매칭 (전력은 sensor_type 참고)
    'sensor_danger':  'RISK_GAS',
    'combined':       'RISK_COMPLEX',
}


def _resolve_risk_category(alarm) -> str:
    """alarm 의 sensor_type 까지 보고 RISK_POWER 도 분기."""
    if alarm.sensor_type == 'power':
        return 'RISK_POWER'
    return ALARM_TYPE_TO_RISK_CODE_FALLBACK.get(alarm.alarm_type, 'RISK_COMMON')


def _resolve_recipients(token: str, alarm=None) -> Iterable[User]:
    """수신자 토큰 → User 객체 iterator.

    Tokens:
      - 'all_users'    : 활성 사용자 전부
      - 'leaders'      : Organization.leader 인 사용자
      - 'group:<id>'   : 특정 조직 소속 사용자
      - 'role:<code>'  : super_admin / admin / operator
    """
    qs = User.objects.filter(is_active=True, is_locked=False)
    if token == 'all_users':
        return qs
    if token == 'leaders':
        # Organization.leader FK 가 None 이 아닌 사용자만
        from .models import Organization
        leader_ids = set(Organization.objects.exclude(leader__isnull=True).values_list('leader_id', flat=True))
        return qs.filter(id__in=leader_ids)
    if token.startswith('group:'):
        try:
            org_id = int(token[6:])
        except ValueError:
            return qs.none()
        return qs.filter(organization_id=org_id)
    if token.startswith('role:'):
        return qs.filter(role=token[5:])
    return qs.none()


def _render_message(template: str, alarm) -> str:
    """간단한 placeholder 치환 — {worker_name}, {device_id}, {value}.
    placeholder 없으면 alarm.message 그대로 반환.
    """
    if not template:
        return alarm.message or ''
    try:
        return template.format(
            worker_name=alarm.worker_name or '-',
            worker_id=alarm.worker_id or '-',
            device_id=alarm.device_id or '-',
            value=alarm.message or '',  # 풀 메시지로 대체
            level=alarm.get_alarm_level_display() if hasattr(alarm, 'get_alarm_level_display') else alarm.alarm_level,
        )
    except (KeyError, IndexError):
        return template  # placeholder 오류 시 raw 템플릿


def _level_priority(alarm_level_str: str) -> int:
    """alerts.alarm_level → 비교 가능한 정수 priority."""
    return {
        'info':     10,
        'caution':  30,
        'danger':   90,
        'critical': 99,
    }.get(alarm_level_str, 0)


@transaction.atomic
def dispatch_for_alarm(alarm) -> int:
    """alarm 1건에 대해 매칭되는 정책을 모두 평가하고 NotificationLog 작성.

    [v6 변경]
      - NotificationLog 를 'pending' 으로 먼저 생성
      - 채널별 Provider.send() 호출
      - 결과로 send_status / error_message / sent_at 갱신
      - 한 사용자 채널 발송 실패해도 다른 (사용자×채널) 진행

    Returns:
        작성된 NotificationLog 건수 (성공/실패 모두 포함).
    """
    from .models import NotificationPolicy, NotificationLog
    from .notification_providers import get_provider

    risk_code = _resolve_risk_category(alarm)
    alarm_priority = _level_priority(alarm.alarm_level)

    policies = NotificationPolicy.objects.filter(
        is_active=True,
        risk_category__code=risk_code,
        alarm_level__priority__lte=alarm_priority,
    ).select_related('risk_category', 'alarm_level')

    created_count = 0
    for policy in policies:
        rendered_msg = _render_message(policy.message_template, alarm)
        seen_user_ids = set()
        for token in policy.recipients_list:
            for user in _resolve_recipients(token, alarm):
                if user.id in seen_user_ids:
                    continue
                seen_user_ids.add(user.id)

                for channel in policy.channels_list:
                    log = NotificationLog.objects.create(
                        policy=policy,
                        alarm=alarm,
                        recipient=user,
                        recipient_name_snapshot=user.first_name or user.username,
                        channel=channel,
                        send_status='pending',
                    )
                    created_count += 1

                    # Provider 호출 (실패 격리)
                    try:
                        provider = get_provider(channel)
                        ok, err = provider.send(user, rendered_msg, log)
                        if ok:
                            log.send_status = 'sent'
                            log.sent_at = timezone.now()
                        else:
                            log.send_status = 'failed' if err else 'skipped'
                            log.error_message = err or ''
                    except Exception as e:
                        log.send_status = 'failed'
                        log.error_message = f'provider_error: {e!r}'[:300]
                        logger.exception('[notify] provider error channel=%s', channel)
                    log.save(update_fields=['send_status', 'sent_at', 'error_message'])

    return created_count


def dispatch_for_notice(notice, *, channels: list[str] | None = None) -> int:
    """공지 게시 시 전체 활성 사용자에게 알림 발송 (옵션).

    [v6] Provider 호출 + send_status 정확히 갱신.

    Returns:
        작성된 NotificationLog 건수 (성공/실패 포함).
    """
    from .models import NotificationLog
    from .notification_providers import get_provider

    channels = channels or ['app', 'realtime']
    msg = f'[공지] {notice.title}'
    n = 0
    for user in User.objects.filter(is_active=True, is_locked=False):
        for ch in channels:
            log = NotificationLog.objects.create(
                policy=None,
                alarm=None,
                recipient=user,
                recipient_name_snapshot=user.first_name or user.username,
                channel=ch,
                send_status='pending',
            )
            n += 1
            try:
                provider = get_provider(ch)
                ok, err = provider.send(user, msg, log)
                if ok:
                    log.send_status = 'sent'
                    log.sent_at = timezone.now()
                else:
                    log.send_status = 'failed' if err else 'skipped'
                    log.error_message = err or ''
            except Exception as e:
                log.send_status = 'failed'
                log.error_message = f'provider_error: {e!r}'[:300]
            log.save(update_fields=['send_status', 'sent_at', 'error_message'])
    return n
