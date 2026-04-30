"""
backoffice/audit.py — 감사 로그 헬퍼.

사용:
  from backoffice.audit import write_audit
  write_audit('create', obj, changes={'name': [None, '홍길동']})

또는 시그널이 자동으로 기록 (TRACKED_MODELS 에 등록된 모델만).
"""

from __future__ import annotations

# Python 3.10 미만에서도 타입힌트에 '|' 구문을 쓸 수 있게 해주는 future import.

import logging

from django.db.models.signals import post_save, post_delete

# post_save: 모델 저장(INSERT/UPDATE) 후 발생하는 시그널.
# post_delete: 모델 삭제(DELETE) 후 발생하는 시그널.

from django.dispatch import receiver

# 시그널과 핸들러 함수를 연결하는 데코레이터.

from .middleware import get_current_user, get_current_ip, get_current_request

# 미들웨어가 thread-local에 저장해 둔 현재 요청자 정보를 가져오는 함수들.
# 시그널은 request 객체를 인자로 받지 않으므로, 이 방식으로 요청 컨텍스트를 꺼냄.


logger = logging.getLogger(__name__)
# 'backoffice.audit' 로거. write_audit 실패 시 경고 로그를 남김.


# 자동 audit 추적 모델 — (app_label, model_name lowercase) 형식
# Django _meta.model_name 이 lowercase 이므로 lowercase 로 등록.
# 추가하면 자동으로 post_save/post_delete 시그널이 기록.
# 빈번한 시스템 트래픽 모델 (SensorData, WorkerLocation, NotificationLog)
# 은 의도적으로 제외 — audit 폭증 방지.
TRACKED_MODELS = {
    # 이 집합에 등록된 모델만 자동으로 감사 로그가 기록됨.
    # (앱 이름, 모델 이름 소문자) 형식의 튜플로 구성.
    ("backoffice", "organization"),
    ("backoffice", "position"),
    ("backoffice", "codegroup"),
    ("backoffice", "code"),
    ("backoffice", "riskcategory"),
    ("backoffice", "risktype"),
    ("backoffice", "alarmlevel"),
    ("backoffice", "thresholdcategory"),
    ("backoffice", "threshold"),
    ("backoffice", "notificationpolicy"),
    ("backoffice", "menupermission"),
    ("backoffice", "dataretentionpolicy"),
    ("backoffice", "notice"),
    ("accounts", "user"),
    ("devices", "device"),
    ("geofence", "geofence"),
    # SensorData, WorkerLocation, NotificationLog는 의도적으로 제외.
    # 이 모델들은 실시간 대량 쓰기가 발생해 audit 기록 시 DB 부하가 폭증함.
}


def write_audit(action: str, obj=None, *, changes=None, message: str = "", actor=None):
    """감사 로그 1건 기록. obj 가 None 이면 시스템 액션 (cleanup 등).

    Args:
        action: 'create' | 'update' | 'delete' | 'login' | 'bulk_op' | ...
        obj: 대상 모델 인스턴스
        changes: dict (예: {'role': ['operator', 'admin']})
        message: 추가 메모
        actor: 명시 actor — 미지정 시 미들웨어 thread-local 에서 가져옴
    """
    from .models import AuditLog

    # 순환 import 방지를 위해 함수 내부에서 import.

    actor = actor or get_current_user()
    # 명시적 actor가 없으면 미들웨어 thread-local에서 현재 요청 사용자를 가져옴.
    actor_username = ""
    if actor and getattr(actor, "is_authenticated", False):
        actor_username = actor.username
        # 실제 로그인 사용자인 경우에만 username을 스냅샷으로 저장.
    else:
        actor = None  # AnonymousUser 등은 None 으로 통일
        # 익명 사용자나 인증되지 않은 객체는 None으로 처리.

    target_app = target_model = target_pk = target_repr = ""
    if obj is not None:
        target_app = obj._meta.app_label
        # Django 모델 메타에서 앱 이름(예: 'backoffice', 'accounts')을 가져옴.
        target_model = obj._meta.model_name
        # Django 모델 메타에서 모델 이름 소문자(예: 'user', 'organization')를 가져옴.
        target_pk = str(obj.pk) if obj.pk is not None else ""
        # 대상 객체의 기본 키(PK)를 문자열로 저장.
        try:
            target_repr = str(obj)[:200]
            # __str__ 메서드 결과를 200자 이내로 잘라서 표시명으로 저장.
            # 대상 삭제 후에도 "무엇을 삭제했는지" 알 수 있도록 스냅샷으로 보존.
        except Exception:
            target_repr = ""

    request = get_current_request()
    request_path = request.path[:500] if request else ""
    # 현재 HTTP 요청의 URL 경로를 500자 이내로 저장. 어떤 API 호출로 변경됐는지 추적.

    try:
        AuditLog.objects.create(
            actor=actor,
            # 액션 수행자 (User FK). 삭제 시 SET_NULL.
            actor_username_snapshot=actor_username,
            # 수행자 username 스냅샷. 사용자 삭제 후에도 "누가 했는지" 보존.
            action=action,
            # 액션 종류: create/update/delete/login 등.
            target_app=target_app,
            target_model=target_model,
            target_pk=target_pk,
            target_repr=target_repr,
            # 변경 대상 객체 정보. FK 대신 문자열로 저장해 대상 삭제 시에도 이력이 남음.
            changes=changes or {},
            # 변경 전후 값. {'field': [old_value, new_value]} 형식.
            ip_address=get_current_ip(),
            # 요청자의 IP 주소. 미들웨어 thread-local에서 가져옴.
            request_path=request_path,
            extra_message=message[:300],
            # 추가 메모. 예: 'CSV 일괄 등록 line 42', '비정상 접근 시도'.
        )
    except Exception as e:
        # 감사 실패가 본 작업을 막아선 안 됨
        logger.warning("[audit] write failed: %r", e)
        # AuditLog 기록 실패가 원래 비즈니스 로직(사용자 생성 등)을 롤백시키지 않도록
        # 예외를 잡아서 경고 로그만 남기고 조용히 넘어감.


# ═══════════════════════════════════════════════════════════
# 자동 시그널 — 등록/수정/삭제 자동 기록
# ═══════════════════════════════════════════════════════════


@receiver(post_save)
# 모든 모델의 저장(INSERT/UPDATE) 후 자동 호출됨. sender=None이면 전체 모델에 발화.
def _auto_audit_save(sender, instance, created, **kwargs):
    key = (sender._meta.app_label, sender._meta.model_name)
    # 저장된 모델의 (앱 이름, 모델 이름) 키를 만들어 TRACKED_MODELS에 있는지 확인.
    if key not in TRACKED_MODELS:
        return
        # 추적 대상이 아닌 모델은 조용히 건너뜀.
    # 마이그레이션 RunPython 안에서 발생하는 시드 저장은 actor 없음 → request 없음
    # 이 경우 audit 안 남김 (DB 시드 vs 사용자 액션 구분)
    if get_current_request() is None:
        return
        # HTTP 요청 컨텍스트 없이 저장된 경우(마이그레이션 시드, 테스트 등)는 기록 안 함.
        # 사람이 백오피스에서 직접 수행한 액션만 감사 로그에 남기는 의도.
    write_audit("create" if created else "update", instance)
    # INSERT면 'create', UPDATE면 'update' 액션으로 감사 로그 1건 작성.


@receiver(post_delete)
# 모든 모델의 삭제(DELETE) 후 자동 호출됨.
def _auto_audit_delete(sender, instance, **kwargs):
    key = (sender._meta.app_label, sender._meta.model_name)
    if key not in TRACKED_MODELS:
        return
    if get_current_request() is None:
        return
    write_audit("delete", instance)
    # 삭제된 객체 정보를 'delete' 액션으로 감사 로그에 기록.
    # obj.pk는 삭제 후에도 잠시 유지되므로 target_pk/target_repr 저장 가능.


# ═══════════════════════════════════════════════════════════
# Device 변경 이력 (DeviceHistory) — 별도 디테일 추적
# ═══════════════════════════════════════════════════════════


@receiver(post_save, sender=None)
# sender=None은 모든 모델에 발화하지만, 함수 본문이 pass라서 실제로 아무것도 하지 않음.
# 향후 장비별 세부 이력을 자동 시그널로 처리하려는 자리 표시자(placeholder)로 보임.
def _device_history_save(sender, instance, created, **kwargs):
    # sender=None 으로 받으면 모든 모델에 발화 — sender 체크
    pass


def write_device_history(device, action: str, changes=None, message: str = ""):
    """장비 변경 이력 1건 기록 — 명시적 호출 헬퍼."""
    # AuditLog와 달리 장비 전용 이력. 장비 상세 화면의 '변경 이력' 탭을 위한 데이터.
    from .models import DeviceHistory

    actor = get_current_user()
    actor_username = ""
    if actor and getattr(actor, "is_authenticated", False):
        actor_username = actor.username
    else:
        actor = None
    try:
        DeviceHistory.objects.create(
            device_id_snapshot=getattr(device, "device_id", "") or "",
            # 장비 고유 ID 스냅샷. 장비 삭제 후에도 "어떤 장비가 바뀌었는지" 보존.
            device=device if device and device.pk else None,
            # 실제 Device FK. 장비 삭제 시 SET_NULL로 자동 해제.
            actor=actor,
            actor_username_snapshot=actor_username,
            # 수행자 username 스냅샷.
            action=action,
            # 장비 액션 종류: create/update/delete/move/toggle/csv_import.
            changes=changes or {},
            # 변경 전후 값 딕셔너리.
            extra_message=message[:300],
            # 추가 메모 (예: 'CSV upsert line 42').
        )
    except Exception as e:
        logger.warning("[device_history] write failed: %r", e)
        # 이력 기록 실패가 원래 장비 저장 작업을 방해하지 않도록 예외를 조용히 처리.


# ═══════════════════════════════════════════════════════════
# 인증 이벤트 추적 — login / logout / login_fail
# ═══════════════════════════════════════════════════════════
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)

# Django 인증 시스템이 제공하는 로그인/로그아웃/로그인실패 전용 시그널.
# 이 시그널들은 Django가 인증 처리 후 자동으로 발생시킴.


@receiver(user_logged_in)
# 사용자가 로그인에 성공하면 자동 호출됨.
def _audit_login(sender, request, user, **kwargs):
    write_audit("login", user, actor=user, message="로그인 성공")
    # 로그인 성공 이벤트를 감사 로그에 기록. actor를 user로 명시해서 미들웨어 없이도 기록.


@receiver(user_logged_out)
# 사용자가 로그아웃하면 자동 호출됨.
def _audit_logout(sender, request, user, **kwargs):
    if user is None:
        return
        # 이미 세션이 만료된 상태에서 로그아웃하면 user가 None일 수 있음.
    write_audit("logout", user, actor=user, message="로그아웃")
    # 로그아웃 이벤트를 감사 로그에 기록.


@receiver(user_login_failed)
# 로그인에 실패하면 자동 호출됨. user 인자 없음 (인증 실패이므로).
def _audit_login_fail(sender, credentials, request=None, **kwargs):
    username = credentials.get("username", "") if credentials else ""
    # 시도한 username을 credentials 딕셔너리에서 가져옴. 없으면 빈 문자열.
    # actor 없음 (인증 실패니까)
    write_audit("login_fail", None, message=f"로그인 실패: username={username}")
    # 어떤 username으로 실패했는지를 메모에 남김. 보안 감사(brute-force 탐지 등)에 활용 가능.
