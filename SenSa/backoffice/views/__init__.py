"""
backoffice/views/ — 백오피스 (슈퍼관리자 채널) 뷰 패키지.

[Phase 2 분리 — 2026-05-06]
  원본: 단일 backoffice/views.py (2,421줄, 16개 도메인 혼재)
  현행: 도메인별 12개 모듈 (이 파일 + _common 제외)

URL 호환성:
  backoffice/urls.py 의 `views.user_list` 같은 참조를 그대로 동작시키기 위해
  본 __init__.py 가 모든 공개 view 함수를 re-export 한다.
  외부 import 예) `from backoffice.views import thresholds_for_fastapi`
                 (mysite/urls.py 가 사용)

모듈 매핑:
  _common.py        — 공통 헬퍼 (_parse_json, _form_errors_payload). 다른 모듈만 사용.
  landing.py        — /backoffice/   메인 랜딩 화면
  users.py          — 사용자 관리 (페이지+API)
  organizations.py  — 조직 관리 (페이지+API)
  positions.py      — 직위 관리 (페이지+API)
  masters.py        — 코어 마스터 (공통 코드/위험 유형/위험 기준/임계치) +
                      FastAPI 동기화용 thresholds_for_fastapi
  events.py         — 이벤트 이력 (Alarm 조회 + CSV)
  notifications.py  — 알림 정책 + 발송 이력 + 메뉴 권한
  devices.py        — 설비/장비 관리 + CSV 일괄 등록
  maps.py           — 지도 편집 (지오펜스) + 평면도 이미지 (v7)
  operations.py     — 운영 데이터 (보관 정책 + v7 백업/초기화)
  notices.py        — 공지사항 관리
  audit.py          — v6 감사 로그 + 장비 변경 이력 모달
"""
# ─── landing ───
from .landing import landing

# ─── users ───
from .users import (
    user_list,
    user_detail_api,
    user_create_api,
    user_update_api,
    user_bulk_delete_api,
    user_bulk_lock_api,
    user_bulk_unlock_api,
)

# ─── organizations ───
from .organizations import (
    organization_manage,
    organization_detail_api,
    organization_create_api,
    organization_update_api,
    organization_delete_api,
    organization_assign_members_api,
    organization_remove_members_api,
    organization_set_leader_api,
    organization_member_picker_api,
)

# ─── positions ───
from .positions import (
    position_list,
    position_detail_api,
    position_create_api,
    position_update_api,
    position_bulk_delete_api,
)

# ─── masters (codes / risks / alarm levels / thresholds + FastAPI sync) ───
from .masters import (
    # 공통 코드
    code_manage,
    code_group_detail_api,
    code_group_create_api,
    code_group_update_api,
    code_group_delete_api,
    code_create_api,
    code_update_api,
    code_bulk_delete_api,
    code_bulk_toggle_api,
    # 위험 유형
    risk_manage,
    risk_cat_detail_api,
    risk_cat_create_api,
    risk_cat_update_api,
    risk_cat_delete_api,
    risk_type_create_api,
    risk_type_update_api,
    risk_type_bulk_delete_api,
    # 위험 기준 (알람 단계)
    alarm_level_list,
    alarm_level_detail_api,
    alarm_level_create_api,
    alarm_level_update_api,
    alarm_level_bulk_delete_api,
    # 임계치
    threshold_manage,
    threshold_cat_detail_api,
    threshold_cat_create_api,
    threshold_cat_update_api,
    threshold_create_api,
    threshold_update_api,
    threshold_bulk_delete_api,
    threshold_bulk_toggle_api,
    # FastAPI 동기화 (mysite/urls.py 가 직접 참조)
    thresholds_for_fastapi,
)

# ─── events ───
from .events import (
    event_history,
    event_history_csv,
    event_detail_api,
    event_bulk_read_api,
)

# ─── notifications (policies + logs + menu perms) ───
from .notifications import (
    notification_policy_list,
    policy_detail_api,
    policy_create_api,
    policy_update_api,
    policy_bulk_delete_api,
    policy_bulk_toggle_api,
    notification_log_list,
    menu_management,
    menu_perm_update_api,
)

# ─── devices ───
from .devices import (
    device_list,
    device_detail_api,
    device_create_api,
    device_update_api,
    device_bulk_delete_api,
    device_bulk_toggle_api,
    device_auto_map_geofence_api,
    device_csv_upload_api,
)

# ─── maps (geofence + map image v7) ───
from .maps import (
    map_edit,
    geofence_detail_api,
    geofence_create_api,
    geofence_update_api,
    geofence_delete_api,
    map_image_list,
    map_image_create_api,
    map_image_update_api,
    map_image_delete_api,
    map_image_toggle_active_api,
)

# ─── operations (retention + v7 backup/init) ───
from .operations import (
    retention_list,
    retention_detail_api,
    retention_update_api,
    retention_run_now_api,
    retention_backup_api,
    retention_init_with_backup_api,
    backup_list,
    backup_preview_api,
    backup_download_api,
    backup_delete_api,
)

# ─── notices ───
from .notices import (
    notice_list,
    notice_detail_api,
    notice_create_api,
    notice_update_api,
    notice_dispatch_api,
    notice_bulk_delete_api,
    notice_bulk_toggle_api,
)

# ─── audit (v6) ───
from .audit import (
    audit_log_list,
    device_history_api,
)


__all__ = [
    # landing
    'landing',
    # users
    'user_list', 'user_detail_api', 'user_create_api', 'user_update_api',
    'user_bulk_delete_api', 'user_bulk_lock_api', 'user_bulk_unlock_api',
    # organizations
    'organization_manage', 'organization_detail_api', 'organization_create_api',
    'organization_update_api', 'organization_delete_api',
    'organization_assign_members_api', 'organization_remove_members_api',
    'organization_set_leader_api', 'organization_member_picker_api',
    # positions
    'position_list', 'position_detail_api', 'position_create_api',
    'position_update_api', 'position_bulk_delete_api',
    # masters
    'code_manage', 'code_group_detail_api', 'code_group_create_api',
    'code_group_update_api', 'code_group_delete_api', 'code_create_api',
    'code_update_api', 'code_bulk_delete_api', 'code_bulk_toggle_api',
    'risk_manage', 'risk_cat_detail_api', 'risk_cat_create_api',
    'risk_cat_update_api', 'risk_cat_delete_api', 'risk_type_create_api',
    'risk_type_update_api', 'risk_type_bulk_delete_api',
    'alarm_level_list', 'alarm_level_detail_api', 'alarm_level_create_api',
    'alarm_level_update_api', 'alarm_level_bulk_delete_api',
    'threshold_manage', 'threshold_cat_detail_api', 'threshold_cat_create_api',
    'threshold_cat_update_api', 'threshold_create_api', 'threshold_update_api',
    'threshold_bulk_delete_api', 'threshold_bulk_toggle_api',
    'thresholds_for_fastapi',
    # events
    'event_history', 'event_history_csv', 'event_detail_api', 'event_bulk_read_api',
    # notifications
    'notification_policy_list', 'policy_detail_api', 'policy_create_api',
    'policy_update_api', 'policy_bulk_delete_api', 'policy_bulk_toggle_api',
    'notification_log_list', 'menu_management', 'menu_perm_update_api',
    # devices
    'device_list', 'device_detail_api', 'device_create_api', 'device_update_api',
    'device_bulk_delete_api', 'device_bulk_toggle_api',
    'device_auto_map_geofence_api', 'device_csv_upload_api',
    # maps
    'map_edit', 'geofence_detail_api', 'geofence_create_api',
    'geofence_update_api', 'geofence_delete_api',
    'map_image_list', 'map_image_create_api', 'map_image_update_api',
    'map_image_delete_api', 'map_image_toggle_active_api',
    # operations
    'retention_list', 'retention_detail_api', 'retention_update_api',
    'retention_run_now_api', 'retention_backup_api', 'retention_init_with_backup_api',
    'backup_list', 'backup_preview_api', 'backup_download_api', 'backup_delete_api',
    # notices
    'notice_list', 'notice_detail_api', 'notice_create_api', 'notice_update_api',
    'notice_dispatch_api', 'notice_bulk_delete_api', 'notice_bulk_toggle_api',
    # audit
    'audit_log_list', 'device_history_api',
]
