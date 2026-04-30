"""
backoffice/urls.py — /backoffice/ 하위 라우팅.

규칙:
  - 페이지: 깔끔한 URL ('users/', 'organizations/', 'positions/')
  - JSON API: 'api/' 프리픽스 (CSRF 는 세션 인증으로 자동 적용)
"""
from django.urls import path

from . import views


app_name = 'backoffice'

urlpatterns = [
    # ═══════════════════════════════════════════════════════
    # 페이지
    # ═══════════════════════════════════════════════════════
    path('', views.landing, name='landing'),

    path('users/',          views.user_list,           name='user-list'),
    path('organizations/',  views.organization_manage, name='org-manage'),
    path('positions/',      views.position_list,       name='position-list'),

    # ═══════════════════════════════════════════════════════
    # 사용자 관리 API
    # ═══════════════════════════════════════════════════════
    path('api/users/<int:pk>/',        views.user_detail_api, name='api-user-detail'),
    path('api/users/create/',          views.user_create_api, name='api-user-create'),
    path('api/users/<int:pk>/update/', views.user_update_api, name='api-user-update'),
    path('api/users/bulk-delete/',     views.user_bulk_delete_api, name='api-user-bulk-delete'),
    path('api/users/bulk-lock/',       views.user_bulk_lock_api,   name='api-user-bulk-lock'),
    path('api/users/bulk-unlock/',     views.user_bulk_unlock_api, name='api-user-bulk-unlock'),

    # ═══════════════════════════════════════════════════════
    # 조직 관리 API
    # ═══════════════════════════════════════════════════════
    path('api/organizations/<int:pk>/',         views.organization_detail_api,         name='api-org-detail'),
    path('api/organizations/create/',           views.organization_create_api,         name='api-org-create'),
    path('api/organizations/<int:pk>/update/',  views.organization_update_api,         name='api-org-update'),
    path('api/organizations/<int:pk>/delete/',  views.organization_delete_api,         name='api-org-delete'),
    path('api/organizations/<int:pk>/assign/',  views.organization_assign_members_api, name='api-org-assign'),
    path('api/organizations/<int:pk>/remove/',  views.organization_remove_members_api, name='api-org-remove'),
    path('api/organizations/<int:pk>/set-leader/', views.organization_set_leader_api, name='api-org-set-leader'),
    path('api/organizations/member-picker/',    views.organization_member_picker_api,  name='api-org-member-picker'),

    # ═══════════════════════════════════════════════════════
    # 직위 관리 API
    # ═══════════════════════════════════════════════════════
    path('api/positions/<int:pk>/',        views.position_detail_api, name='api-position-detail'),
    path('api/positions/create/',          views.position_create_api, name='api-position-create'),
    path('api/positions/<int:pk>/update/', views.position_update_api, name='api-position-update'),
    path('api/positions/bulk-delete/',     views.position_bulk_delete_api, name='api-position-bulk-delete'),

    # ═══════════════════════════════════════════════════════
    # 공통 코드 관리
    # ═══════════════════════════════════════════════════════
    path('codes/', views.code_manage, name='code-manage'),
    path('api/code-groups/<int:pk>/',          views.code_group_detail_api,  name='api-cg-detail'),
    path('api/code-groups/create/',            views.code_group_create_api,  name='api-cg-create'),
    path('api/code-groups/<int:pk>/update/',   views.code_group_update_api,  name='api-cg-update'),
    path('api/code-groups/<int:pk>/delete/',   views.code_group_delete_api,  name='api-cg-delete'),
    path('api/codes/create/',                  views.code_create_api,        name='api-code-create'),
    path('api/codes/<int:pk>/update/',         views.code_update_api,        name='api-code-update'),
    path('api/codes/bulk-delete/',             views.code_bulk_delete_api,   name='api-code-bulk-delete'),
    path('api/codes/bulk-toggle/',             views.code_bulk_toggle_api,   name='api-code-bulk-toggle'),

    # ═══════════════════════════════════════════════════════
    # 위험 유형 관리
    # ═══════════════════════════════════════════════════════
    path('risks/', views.risk_manage, name='risk-manage'),
    path('api/risk-categories/<int:pk>/',         views.risk_cat_detail_api,    name='api-risk-cat-detail'),
    path('api/risk-categories/create/',           views.risk_cat_create_api,    name='api-risk-cat-create'),
    path('api/risk-categories/<int:pk>/update/',  views.risk_cat_update_api,    name='api-risk-cat-update'),
    path('api/risk-categories/<int:pk>/delete/',  views.risk_cat_delete_api,    name='api-risk-cat-delete'),
    path('api/risk-types/create/',                views.risk_type_create_api,   name='api-risk-type-create'),
    path('api/risk-types/<int:pk>/update/',       views.risk_type_update_api,   name='api-risk-type-update'),
    path('api/risk-types/bulk-delete/',           views.risk_type_bulk_delete_api, name='api-risk-type-bulk-delete'),

    # ═══════════════════════════════════════════════════════
    # 위험 기준 (알람 단계) 관리
    # ═══════════════════════════════════════════════════════
    path('alarm-levels/', views.alarm_level_list, name='alarm-level-list'),
    path('api/alarm-levels/<int:pk>/',          views.alarm_level_detail_api,    name='api-al-detail'),
    path('api/alarm-levels/create/',            views.alarm_level_create_api,    name='api-al-create'),
    path('api/alarm-levels/<int:pk>/update/',   views.alarm_level_update_api,    name='api-al-update'),
    path('api/alarm-levels/bulk-delete/',       views.alarm_level_bulk_delete_api, name='api-al-bulk-delete'),

    # ═══════════════════════════════════════════════════════
    # 임계치 기준 관리
    # ═══════════════════════════════════════════════════════
    path('thresholds/', views.threshold_manage, name='threshold-manage'),
    path('api/threshold-categories/<int:pk>/',         views.threshold_cat_detail_api,  name='api-th-cat-detail'),
    path('api/threshold-categories/create/',           views.threshold_cat_create_api,  name='api-th-cat-create'),
    path('api/threshold-categories/<int:pk>/update/',  views.threshold_cat_update_api,  name='api-th-cat-update'),
    path('api/thresholds/create/',                     views.threshold_create_api,      name='api-th-create'),
    path('api/thresholds/<int:pk>/update/',            views.threshold_update_api,      name='api-th-update'),
    path('api/thresholds/bulk-delete/',                views.threshold_bulk_delete_api, name='api-th-bulk-delete'),
    path('api/thresholds/bulk-toggle/',                views.threshold_bulk_toggle_api, name='api-th-bulk-toggle'),

    # ═══════════════════════════════════════════════════════
    # 이벤트 이력 관리 (alerts.Alarm 조회)
    # ═══════════════════════════════════════════════════════
    path('events/',         views.event_history,     name='event-history'),
    path('events/csv/',     views.event_history_csv, name='event-history-csv'),
    path('api/events/<int:pk>/',     views.event_detail_api,  name='api-event-detail'),
    path('api/events/bulk-read/',    views.event_bulk_read_api, name='api-event-bulk-read'),

    # ═══════════════════════════════════════════════════════
    # 알림 정책 관리
    # ═══════════════════════════════════════════════════════
    path('notification-policies/', views.notification_policy_list, name='policy-list'),
    path('api/policies/<int:pk>/',           views.policy_detail_api,      name='api-policy-detail'),
    path('api/policies/create/',             views.policy_create_api,      name='api-policy-create'),
    path('api/policies/<int:pk>/update/',    views.policy_update_api,      name='api-policy-update'),
    path('api/policies/bulk-delete/',        views.policy_bulk_delete_api, name='api-policy-bulk-delete'),
    path('api/policies/bulk-toggle/',        views.policy_bulk_toggle_api, name='api-policy-bulk-toggle'),

    # ═══════════════════════════════════════════════════════
    # 알림 발송 이력
    # ═══════════════════════════════════════════════════════
    path('notification-logs/', views.notification_log_list, name='notification-log-list'),

    # ═══════════════════════════════════════════════════════
    # 메뉴 관리 (역할별 메뉴 권한)
    # ═══════════════════════════════════════════════════════
    path('menus/', views.menu_management, name='menu-manage'),
    path('api/menu-perms/update/', views.menu_perm_update_api, name='api-menu-perm-update'),

    # ═══════════════════════════════════════════════════════
    # 설비/장비 관리
    # ═══════════════════════════════════════════════════════
    path('devices/', views.device_list, name='device-list'),
    path('api/devices/<int:pk>/',         views.device_detail_api,      name='api-device-detail'),
    path('api/devices/create/',           views.device_create_api,      name='api-device-create'),
    path('api/devices/<int:pk>/update/',  views.device_update_api,      name='api-device-update'),
    path('api/devices/bulk-delete/',      views.device_bulk_delete_api, name='api-device-bulk-delete'),
    path('api/devices/bulk-toggle/',      views.device_bulk_toggle_api, name='api-device-bulk-toggle'),
    path('api/devices/auto-map/',         views.device_auto_map_geofence_api, name='api-device-auto-map'),
    path('api/devices/csv-upload/',       views.device_csv_upload_api,  name='api-device-csv-upload'),

    # ═══════════════════════════════════════════════════════
    # 지도 편집 관리
    # ═══════════════════════════════════════════════════════
    path('maps/', views.map_edit, name='map-edit'),
    path('api/geofences/<int:pk>/',         views.geofence_detail_api, name='api-gf-detail'),
    path('api/geofences/create/',           views.geofence_create_api, name='api-gf-create'),
    path('api/geofences/<int:pk>/update/',  views.geofence_update_api, name='api-gf-update'),
    path('api/geofences/<int:pk>/delete/',  views.geofence_delete_api, name='api-gf-delete'),

    # ═══════════════════════════════════════════════════════
    # 운영 데이터 관리 (보관 정책)
    # ═══════════════════════════════════════════════════════
    path('operations/retention/', views.retention_list, name='retention-list'),
    path('api/retention/<int:pk>/',         views.retention_detail_api, name='api-retention-detail'),
    path('api/retention/<int:pk>/update/',  views.retention_update_api, name='api-retention-update'),
    path('api/retention/<int:pk>/run-now/', views.retention_run_now_api, name='api-retention-run-now'),

    # ═══════════════════════════════════════════════════════
    # 공지사항 관리
    # ═══════════════════════════════════════════════════════
    path('notices/', views.notice_list, name='notice-list'),
    path('api/notices/<int:pk>/',        views.notice_detail_api,        name='api-notice-detail'),
    path('api/notices/create/',          views.notice_create_api,        name='api-notice-create'),
    path('api/notices/<int:pk>/update/', views.notice_update_api,        name='api-notice-update'),
    path('api/notices/<int:pk>/dispatch/', views.notice_dispatch_api,    name='api-notice-dispatch'),
    path('api/notices/bulk-delete/',     views.notice_bulk_delete_api,   name='api-notice-bulk-delete'),
    path('api/notices/bulk-toggle/',     views.notice_bulk_toggle_api,   name='api-notice-bulk-toggle'),

    # ═══════════════════════════════════════════════════════
    # v6 — 감사 로그 + 장비 변경 이력
    # ═══════════════════════════════════════════════════════
    path('audit-logs/', views.audit_log_list, name='audit-log-list'),
    path('api/devices/<int:pk>/history/', views.device_history_api, name='api-device-history'),
]
