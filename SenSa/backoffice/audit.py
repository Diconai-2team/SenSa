"""
backoffice/audit.py — 감사 로그 헬퍼.

사용:
  from backoffice.audit import write_audit
  write_audit('create', obj, changes={'name': [None, '홍길동']})

또는 시그널이 자동으로 기록 (TRACKED_MODELS 에 등록된 모델만).
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .middleware import get_current_user, get_current_ip, get_current_request


logger = logging.getLogger(__name__)


# 자동 audit 추적 모델 — (app_label, model_name lowercase) 형식
# Django _meta.model_name 이 lowercase 이므로 lowercase 로 등록.
# 추가하면 자동으로 post_save/post_delete 시그널이 기록.
# 빈번한 시스템 트래픽 모델 (SensorData, WorkerLocation, NotificationLog)
# 은 의도적으로 제외 — audit 폭증 방지.
TRACKED_MODELS = {
    ('backoffice', 'organization'),
    ('backoffice', 'position'),
    ('backoffice', 'codegroup'),
    ('backoffice', 'code'),
    ('backoffice', 'riskcategory'),
    ('backoffice', 'risktype'),
    ('backoffice', 'alarmlevel'),
    ('backoffice', 'thresholdcategory'),
    ('backoffice', 'threshold'),
    ('backoffice', 'notificationpolicy'),
    ('backoffice', 'menupermission'),
    ('backoffice', 'dataretentionpolicy'),
    ('backoffice', 'notice'),
    ('accounts', 'user'),
    ('devices', 'device'),
    ('geofence', 'geofence'),
}


def write_audit(action: str, obj=None, *, changes=None, message: str = '', actor=None):
    """감사 로그 1건 기록. obj 가 None 이면 시스템 액션 (cleanup 등).

    Args:
        action: 'create' | 'update' | 'delete' | 'login' | 'bulk_op' | ...
        obj: 대상 모델 인스턴스
        changes: dict (예: {'role': ['operator', 'admin']})
        message: 추가 메모
        actor: 명시 actor — 미지정 시 미들웨어 thread-local 에서 가져옴
    """
    from .models import AuditLog

    actor = actor or get_current_user()
    actor_username = ''
    if actor and getattr(actor, 'is_authenticated', False):
        actor_username = actor.username
    else:
        actor = None  # AnonymousUser 등은 None 으로 통일

    target_app = target_model = target_pk = target_repr = ''
    if obj is not None:
        target_app = obj._meta.app_label
        target_model = obj._meta.model_name
        target_pk = str(obj.pk) if obj.pk is not None else ''
        try:
            target_repr = str(obj)[:200]
        except Exception:
            target_repr = ''

    request = get_current_request()
    request_path = request.path[:500] if request else ''

    try:
        AuditLog.objects.create(
            actor=actor,
            actor_username_snapshot=actor_username,
            action=action,
            target_app=target_app,
            target_model=target_model,
            target_pk=target_pk,
            target_repr=target_repr,
            changes=changes or {},
            ip_address=get_current_ip(),
            request_path=request_path,
            extra_message=message[:300],
        )
    except Exception as e:
        # 감사 실패가 본 작업을 막아선 안 됨
        logger.warning('[audit] write failed: %r', e)


# ═══════════════════════════════════════════════════════════
# 자동 시그널 — 등록/수정/삭제 자동 기록
# ═══════════════════════════════════════════════════════════

@receiver(post_save)
def _auto_audit_save(sender, instance, created, **kwargs):
    key = (sender._meta.app_label, sender._meta.model_name)
    if key not in TRACKED_MODELS:
        return
    # 마이그레이션 RunPython 안에서 발생하는 시드 저장은 actor 없음 → request 없음
    # 이 경우 audit 안 남김 (DB 시드 vs 사용자 액션 구분)
    if get_current_request() is None:
        return
    write_audit('create' if created else 'update', instance)


@receiver(post_delete)
def _auto_audit_delete(sender, instance, **kwargs):
    key = (sender._meta.app_label, sender._meta.model_name)
    if key not in TRACKED_MODELS:
        return
    if get_current_request() is None:
        return
    write_audit('delete', instance)


# ═══════════════════════════════════════════════════════════
# Device 변경 이력 (DeviceHistory) — 별도 디테일 추적
# ═══════════════════════════════════════════════════════════

@receiver(post_save, sender=None)
def _device_history_save(sender, instance, created, **kwargs):
    # sender=None 으로 받으면 모든 모델에 발화 — sender 체크
    pass


def write_device_history(device, action: str, changes=None, message: str = ''):
    """장비 변경 이력 1건 기록 — 명시적 호출 헬퍼."""
    from .models import DeviceHistory
    actor = get_current_user()
    actor_username = ''
    if actor and getattr(actor, 'is_authenticated', False):
        actor_username = actor.username
    else:
        actor = None
    try:
        DeviceHistory.objects.create(
            device_id_snapshot=getattr(device, 'device_id', '') or '',
            device=device if device and device.pk else None,
            actor=actor,
            actor_username_snapshot=actor_username,
            action=action,
            changes=changes or {},
            extra_message=message[:300],
        )
    except Exception as e:
        logger.warning('[device_history] write failed: %r', e)


# ═══════════════════════════════════════════════════════════
# 인증 이벤트 추적 — login / logout / login_fail
# ═══════════════════════════════════════════════════════════
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed


@receiver(user_logged_in)
def _audit_login(sender, request, user, **kwargs):
    write_audit('login', user, actor=user, message=f'로그인 성공')


@receiver(user_logged_out)
def _audit_logout(sender, request, user, **kwargs):
    if user is None:
        return
    write_audit('logout', user, actor=user, message='로그아웃')


@receiver(user_login_failed)
def _audit_login_fail(sender, credentials, request=None, **kwargs):
    username = credentials.get('username', '') if credentials else ''
    # actor 없음 (인증 실패니까)
    write_audit('login_fail', None, message=f'로그인 실패: username={username}')
