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

# Python 3.10 미만에서도 'X | Y' 타입힌트 문법을 쓸 수 있게 허용하는 future import.

import logging
from typing import Iterable

# 반환 타입 힌트에 사용. _resolve_recipients가 User 객체의 이터러블을 반환함을 표현.

from django.contrib.auth import get_user_model

# 프로젝트의 커스텀 User 모델을 가져오는 함수. User를 직접 import하면 순환 의존 발생 가능.

from django.db import transaction

# 여러 DB 쓰기를 하나의 트랜잭션으로 묶는 컨텍스트 매니저.
# dispatch_for_alarm이 @transaction.atomic이므로, 중간에 예외 발생 시 전체 롤백됨.

from django.utils import timezone

# Django 타임존 인식 현재 시각을 반환하는 유틸리티. sent_at 필드에 사용.


logger = logging.getLogger(__name__)
# 'backoffice.notification_dispatcher' 로거. Provider 에러 등을 기록.

User = get_user_model()
# 프로젝트 커스텀 User 모델 클래스. accounts.User.


# alerts.alarm_level('info'/'caution'/'danger'/'critical') ↔ AlarmLevel.code 매핑
# alerts 의 'info' 는 백오피스에 정의된 게 없으므로 정책 매칭 우선순위 NORMAL 로 매핑.
ALARM_LEVEL_TO_CODE = {
    # alerts.Alarm 모델의 alarm_level 문자열 → 백오피스 AlarmLevel.code로 변환하는 매핑표.
    "info": "NORMAL",
    "caution": "CAUTION",
    "danger": "DANGER",
    "critical": "DANGER",
    # 'critical'은 별도 AlarmLevel이 없으므로 가장 높은 'DANGER'에 매핑.
}

# alerts.alarm_type ↔ RiskCategory.code 매핑 (휴리스틱)
# alerts.Alarm 의 alarm_type:
#   geofence_enter / sensor_caution / sensor_danger / combined
# RiskCategory.code: RISK_GAS / RISK_POWER / RISK_LOCATION / RISK_WORK / ...
ALARM_TYPE_TO_RISK_CODE_FALLBACK = {
    # 알람 타입별 위험 분류 코드 매핑. sensor_type이 'power'인 경우는 아래에서 별도 처리.
    "geofence_enter": "RISK_LOCATION",
    # 지오펜스 진입 알람 → 위치 위험 분류.
    "sensor_caution": "RISK_GAS",  # 센서 = 가스 매칭 (전력은 sensor_type 참고)
    "sensor_danger": "RISK_GAS",
    # 센서 경보는 기본적으로 가스 위험으로 분류. 전력 센서는 _resolve_risk_category에서 별도 처리.
    "combined": "RISK_COMPLEX",
    # 복합 알람 → 복합 위험 분류.
}


def _resolve_risk_category(alarm) -> str:
    """alarm 의 sensor_type 까지 보고 RISK_POWER 도 분기."""
    if alarm.sensor_type == "power":
        return "RISK_POWER"
        # 전력 센서 알람은 가스가 아닌 전력 위험 분류로 매핑.
    return ALARM_TYPE_TO_RISK_CODE_FALLBACK.get(alarm.alarm_type, "RISK_COMMON")
    # 알람 타입에 매핑된 위험 분류 코드 반환. 매핑이 없으면 'RISK_COMMON' 기본값.


def _resolve_recipients(token: str, alarm=None) -> Iterable[User]:
    """수신자 토큰 → User 객체 iterator.

    Tokens:
      - 'all_users'    : 활성 사용자 전부
      - 'leaders'      : Organization.leader 인 사용자
      - 'group:<id>'   : 특정 조직 소속 사용자
      - 'role:<code>'  : super_admin / admin / operator
    """
    qs = User.objects.filter(is_active=True, is_locked=False)
    # 기본 쿼리셋: 활성 상태이고 잠금되지 않은 사용자만 대상으로 함.
    if token == "all_users":
        return qs
        # 전체 활성 사용자에게 발송.
    if token == "leaders":
        # Organization.leader FK 가 None 이 아닌 사용자만
        from .models import Organization

        leader_ids = set(
            Organization.objects.exclude(leader__isnull=True).values_list(
                "leader_id", flat=True
            )
        )
        # 조직장으로 지정된 사용자의 ID 집합을 가져옴.
        return qs.filter(id__in=leader_ids)
        # 조직장인 활성 사용자만 필터링.
    if token.startswith("group:"):
        try:
            org_id = int(token[6:])
            # 'group:5' → org_id=5 로 변환.
        except ValueError:
            return qs.none()
            # 숫자가 아닌 그룹 ID면 빈 결과 반환.
        return qs.filter(organization_id=org_id)
        # 특정 조직에 소속된 활성 사용자만 필터링.
    if token.startswith("role:"):
        return qs.filter(role=token[5:])
        # 'role:admin' → role='admin'인 사용자만 필터링.
    return qs.none()
    # 알 수 없는 토큰이면 빈 결과 반환.


def _render_message(template: str, alarm) -> str:
    """간단한 placeholder 치환 — {worker_name}, {device_id}, {value}.
    placeholder 없으면 alarm.message 그대로 반환.
    """
    if not template:
        return alarm.message or ""
        # 정책에 템플릿이 없으면 알람 자체의 메시지를 그대로 사용.
    try:
        return template.format(
            worker_name=alarm.worker_name or "-",
            # {worker_name} → 알람과 연관된 작업자 이름.
            worker_id=alarm.worker_id or "-",
            device_id=alarm.device_id or "-",
            # {device_id} → 알람을 발생시킨 센서 장비 ID.
            value=alarm.message or "",  # 풀 메시지로 대체
            level=(
                alarm.get_alarm_level_display()
                if hasattr(alarm, "get_alarm_level_display")
                else alarm.alarm_level
            ),
            # {level} → '주의', '위험' 등 알람 단계의 표시용 문자열.
        )
    except (KeyError, IndexError):
        return template  # placeholder 오류 시 raw 템플릿
        # 템플릿에 잘못된 placeholder가 있으면 치환 없이 원문 그대로 반환.


def _level_priority(alarm_level_str: str) -> int:
    """alerts.alarm_level → 비교 가능한 정수 priority."""
    return {
        # 알람 레벨 문자열을 정수 우선순위로 변환.
        # 정책의 alarm_level.priority와 비교해서 이 알람이 정책 적용 기준을 충족하는지 판단.
        "info": 10,
        "caution": 30,
        "danger": 90,
        "critical": 99,
    }.get(alarm_level_str, 0)
    # 알 수 없는 레벨이면 0 반환 (어떤 정책과도 매칭되지 않음).


@transaction.atomic
# 이 함수 전체를 하나의 DB 트랜잭션으로 묶음.
# 중간에 예외 발생 시 작성된 NotificationLog 전체가 롤백되어 불완전한 이력이 남지 않음.
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

    # 순환 import 방지를 위해 함수 내부에서 import.

    risk_code = _resolve_risk_category(alarm)
    # 알람의 센서 타입과 알람 타입을 보고 위험 분류 코드(RISK_GAS 등)를 결정.

    alarm_priority = _level_priority(alarm.alarm_level)
    # 이 알람의 레벨을 정수 우선순위로 변환 (info=10, danger=90 등).

    policies = NotificationPolicy.objects.filter(
        is_active=True,
        risk_category__code=risk_code,
        # 이 알람의 위험 분류와 일치하는 정책만 조회.
        alarm_level__priority__lte=alarm_priority,
        # "이 알람 단계 이상(lte: 우선순위 숫자가 작을수록 높음)"에 적용되는 정책만 조회.
        # 예: alarm_priority=90(danger)이면 priority≤90인 정책(caution, danger 등) 모두 매칭.
    ).select_related("risk_category", "alarm_level")
    # 연관 테이블을 JOIN으로 한 번에 조회하여 쿼리 수를 줄임.

    created_count = 0
    for policy in policies:
        rendered_msg = _render_message(policy.message_template, alarm)
        # 정책의 메시지 템플릿에 알람 정보를 치환하여 실제 발송할 문자열을 만듦.
        seen_user_ids = set()
        # 중복 수신 방지: 한 사용자가 여러 토큰에 해당되어도 1번만 발송.
        for token in policy.recipients_list:
            # recipients_csv를 파싱한 토큰 목록 순회 (예: ['all_users', 'group:3']).
            for user in _resolve_recipients(token, alarm):
                if user.id in seen_user_ids:
                    continue
                    # 이미 이 정책에서 처리한 사용자면 건너뜀. 중복 발송 방지.
                seen_user_ids.add(user.id)

                for channel in policy.channels_list:
                    # channels_csv를 파싱한 채널 목록 순회 (예: ['app', 'email']).
                    log = NotificationLog.objects.create(
                        policy=policy,
                        alarm=alarm,
                        recipient=user,
                        recipient_name_snapshot=user.first_name or user.username,
                        # 수신자 이름 스냅샷. 사용자 삭제 후에도 "누가 받았는지" 보존.
                        channel=channel,
                        send_status="pending",
                        # 먼저 'pending' 상태로 기록하고, Provider 발송 결과에 따라 업데이트.
                    )
                    created_count += 1

                    # Provider 호출 (실패 격리)
                    try:
                        provider = get_provider(channel)
                        # 채널에 맞는 Provider 인스턴스 가져옴 (email → EmailProvider 등).
                        ok, err = provider.send(user, rendered_msg, log)
                        # 실제 발송 시도. (성공 여부, 에러 메시지) 튜플 반환.
                        if ok:
                            log.send_status = "sent"
                            log.sent_at = timezone.now()
                            # 발송 성공: 'sent' + 발송 시각 기록.
                        else:
                            log.send_status = "failed" if err else "skipped"
                            # 에러 메시지 있으면 'failed', 없으면 'skipped' (예: 토큰 없음).
                            log.error_message = err or ""
                    except Exception as e:
                        log.send_status = "failed"
                        log.error_message = f"provider_error: {e!r}"[:300]
                        # Provider 자체에서 예외 발생 시(SMTP 연결 실패 등) 'failed' 처리.
                        logger.exception("[notify] provider error channel=%s", channel)
                        # 이 예외는 잡아서 다음 (사용자×채널) 조합 발송을 계속 진행.
                    log.save(update_fields=["send_status", "sent_at", "error_message"])
                    # 발송 결과로 NotificationLog 상태 필드만 업데이트.

    return created_count
    # 이 알람에 대해 작성된 총 NotificationLog 건수 반환.


def dispatch_for_notice(notice, *, channels: list[str] | None = None) -> int:
    """공지 게시 시 전체 활성 사용자에게 알림 발송 (옵션).

    [v6] Provider 호출 + send_status 정확히 갱신.

    Returns:
        작성된 NotificationLog 건수 (성공/실패 포함).
    """
    from .models import NotificationLog
    from .notification_providers import get_provider

    channels = channels or ["app", "realtime"]
    # 채널 미지정 시 기본으로 앱 푸시 + 실시간 관제에 발송.
    msg = f"[공지] {notice.title}"
    # 공지 알림 메시지는 고정 형식. 실제 공지 내용은 링크로 접근하는 방식이 일반적.
    n = 0
    for user in User.objects.filter(is_active=True, is_locked=False):
        # 활성 상태이고 잠금되지 않은 모든 사용자에게 발송.
        for ch in channels:
            log = NotificationLog.objects.create(
                policy=None,
                # 공지 알림은 특정 NotificationPolicy 없이 발송.
                alarm=None,
                # 공지 알림은 알람 이벤트와 무관.
                recipient=user,
                recipient_name_snapshot=user.first_name or user.username,
                channel=ch,
                send_status="pending",
            )
            n += 1
            try:
                provider = get_provider(ch)
                ok, err = provider.send(user, msg, log)
                if ok:
                    log.send_status = "sent"
                    log.sent_at = timezone.now()
                else:
                    log.send_status = "failed" if err else "skipped"
                    log.error_message = err or ""
            except Exception as e:
                log.send_status = "failed"
                log.error_message = f"provider_error: {e!r}"[:300]
                # 한 사용자 발송 실패해도 다음 사용자 발송 계속 진행.
            log.save(update_fields=["send_status", "sent_at", "error_message"])
    return n
    # 총 작성된 NotificationLog 건수 반환.
