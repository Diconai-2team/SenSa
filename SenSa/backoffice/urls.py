"""
backoffice/urls.py — /backoffice/ 하위 라우팅.

규칙:
  - 페이지: 깔끔한 URL ('users/', 'organizations/', 'positions/')
  - JSON API: 'api/' 프리픽스 (CSRF 는 세션 인증으로 자동 적용)
"""

from django.urls import path

# URL 패턴을 정의하는 Django 기본 함수.

from . import views

# 이 패키지(backoffice/)의 views.py를 가져옴. 모든 뷰 함수가 여기에 정의되어 있음.


app_name = "backoffice"
# URL 네임스페이스. 템플릿에서 {% url 'backoffice:user-list' %} 형식으로 참조할 때 사용.

urlpatterns = [
    # ═══════════════════════════════════════════════════════
    # 페이지
    # ═══════════════════════════════════════════════════════
    path("", views.landing, name="landing"),
    # /backoffice/ → 백오피스 메인 랜딩 페이지 (사용자/조직/직위 통계 카드 표시).
    path("users/", views.user_list, name="user-list"),
    # /backoffice/users/ → 사용자 관리 목록 페이지 (검색/필터/정렬/페이지네이션 포함).
    path("organizations/", views.organization_manage, name="org-manage"),
    # /backoffice/organizations/ → 조직(회사+부서) 관리 페이지 (좌: 트리, 우: 구성원 상세).
    path("positions/", views.position_list, name="position-list"),
    # /backoffice/positions/ → 직위 마스터 관리 목록 페이지.
    # ═══════════════════════════════════════════════════════
    # 사용자 관리 API
    # ═══════════════════════════════════════════════════════
    path("api/users/<int:pk>/", views.user_detail_api, name="api-user-detail"),
    # GET: 사용자 1건 상세 정보 반환 (모달 표시용).
    path("api/users/create/", views.user_create_api, name="api-user-create"),
    # POST: 신규 사용자 등록. 요청 body에 사용자 정보 JSON 포함.
    path("api/users/<int:pk>/update/", views.user_update_api, name="api-user-update"),
    # POST: 사용자 정보 수정 (이름, 역할, 조직, 직위 등).
    path(
        "api/users/bulk-delete/",
        views.user_bulk_delete_api,
        name="api-user-bulk-delete",
    ),
    # POST: 체크박스 선택된 사용자 일괄 삭제. body: {"ids": [1, 2, 3]}.
    path("api/users/bulk-lock/", views.user_bulk_lock_api, name="api-user-bulk-lock"),
    # POST: 선택된 사용자 일괄 잠금(로그인 차단). body: {"ids": [...]}.
    path(
        "api/users/bulk-unlock/",
        views.user_bulk_unlock_api,
        name="api-user-bulk-unlock",
    ),
    # POST: 선택된 사용자 일괄 잠금 해제.
    # ═══════════════════════════════════════════════════════
    # 조직 관리 API
    # ═══════════════════════════════════════════════════════
    path(
        "api/organizations/<int:pk>/",
        views.organization_detail_api,
        name="api-org-detail",
    ),
    # GET: 조직 1건 상세 + 소속 구성원 목록 반환.
    path(
        "api/organizations/create/",
        views.organization_create_api,
        name="api-org-create",
    ),
    # POST: 새 조직(부서) 등록.
    path(
        "api/organizations/<int:pk>/update/",
        views.organization_update_api,
        name="api-org-update",
    ),
    # POST: 조직 정보 수정 (이름, 코드, 설명 등).
    path(
        "api/organizations/<int:pk>/delete/",
        views.organization_delete_api,
        name="api-org-delete",
    ),
    # POST: 조직(부서) 삭제. 소속 사용자는 '조직 없음' 버킷으로 자동 이동.
    path(
        "api/organizations/<int:pk>/assign/",
        views.organization_assign_members_api,
        name="api-org-assign",
    ),
    # POST: 사용자를 이 조직으로 이동(구성원 추가). body: {"user_ids": [...]}.
    path(
        "api/organizations/<int:pk>/remove/",
        views.organization_remove_members_api,
        name="api-org-remove",
    ),
    # POST: 사용자를 이 조직에서 제외 → '조직 없음'으로 이동.
    path(
        "api/organizations/<int:pk>/set-leader/",
        views.organization_set_leader_api,
        name="api-org-set-leader",
    ),
    # POST: 조직장 임명. body: {"user_id": ...} (단건만 가능).
    path(
        "api/organizations/member-picker/",
        views.organization_member_picker_api,
        name="api-org-member-picker",
    ),
    # GET: 구성원 추가 팝업에서 사용자 검색 목록 제공. ?org_id= 로 특정 조직 구성원 표시.
    # ═══════════════════════════════════════════════════════
    # 직위 관리 API
    # ═══════════════════════════════════════════════════════
    path(
        "api/positions/<int:pk>/", views.position_detail_api, name="api-position-detail"
    ),
    # GET: 직위 1건 상세 정보 반환 (모달 표시용).
    path(
        "api/positions/create/", views.position_create_api, name="api-position-create"
    ),
    # POST: 새 직위 등록 (직위명, 정렬 순서, 설명 등).
    path(
        "api/positions/<int:pk>/update/",
        views.position_update_api,
        name="api-position-update",
    ),
    # POST: 직위 정보 수정.
    path(
        "api/positions/bulk-delete/",
        views.position_bulk_delete_api,
        name="api-position-bulk-delete",
    ),
    # POST: 선택된 직위 일괄 삭제.
    # ═══════════════════════════════════════════════════════
    # 공통 코드 관리
    # ═══════════════════════════════════════════════════════
    path("codes/", views.code_manage, name="code-manage"),
    # /backoffice/codes/ → 공통 코드 관리 페이지 (좌: 코드 그룹 목록, 우: 그룹별 코드 목록).
    path(
        "api/code-groups/<int:pk>/", views.code_group_detail_api, name="api-cg-detail"
    ),
    # GET: 코드 그룹 1건 상세 + 하위 코드 목록 반환.
    path("api/code-groups/create/", views.code_group_create_api, name="api-cg-create"),
    # POST: 새 코드 그룹 등록 (예: DEVICE_TYPE, GAS_TYPE 등).
    path(
        "api/code-groups/<int:pk>/update/",
        views.code_group_update_api,
        name="api-cg-update",
    ),
    # POST: 코드 그룹 정보 수정.
    path(
        "api/code-groups/<int:pk>/delete/",
        views.code_group_delete_api,
        name="api-cg-delete",
    ),
    # POST: 코드 그룹 삭제. is_system=True인 시스템 그룹은 삭제 불가.
    path("api/codes/create/", views.code_create_api, name="api-code-create"),
    # POST: 코드 그룹 안에 새 코드 항목 등록 (예: GAS_TYPE 그룹 안에 CO, H2S 등).
    path("api/codes/<int:pk>/update/", views.code_update_api, name="api-code-update"),
    # POST: 코드 항목 정보 수정.
    path(
        "api/codes/bulk-delete/",
        views.code_bulk_delete_api,
        name="api-code-bulk-delete",
    ),
    # POST: 선택된 코드 항목 일괄 삭제.
    path(
        "api/codes/bulk-toggle/",
        views.code_bulk_toggle_api,
        name="api-code-bulk-toggle",
    ),
    # POST: 선택된 코드 항목의 is_active(사용 여부) 일괄 변경.
    # ═══════════════════════════════════════════════════════
    # 위험 유형 관리
    # ═══════════════════════════════════════════════════════
    path("risks/", views.risk_manage, name="risk-manage"),
    # /backoffice/risks/ → 위험 유형 관리 페이지 (분류 + 유형 2레벨 구조).
    path(
        "api/risk-categories/<int:pk>/",
        views.risk_cat_detail_api,
        name="api-risk-cat-detail",
    ),
    # GET: 위험 분류 1건 상세 + 하위 위험 유형 목록 반환.
    path(
        "api/risk-categories/create/",
        views.risk_cat_create_api,
        name="api-risk-cat-create",
    ),
    # POST: 새 위험 분류 등록 (예: RISK_GAS, RISK_POWER, RISK_LOCATION).
    path(
        "api/risk-categories/<int:pk>/update/",
        views.risk_cat_update_api,
        name="api-risk-cat-update",
    ),
    # POST: 위험 분류 정보 수정.
    path(
        "api/risk-categories/<int:pk>/delete/",
        views.risk_cat_delete_api,
        name="api-risk-cat-delete",
    ),
    # POST: 위험 분류 삭제. is_system=True인 시스템 분류는 삭제 불가.
    path(
        "api/risk-types/create/",
        views.risk_type_create_api,
        name="api-risk-type-create",
    ),
    # POST: 위험 분류 아래에 새 위험 유형 등록 (예: RISK_GAS 아래 GAS_LEAK, GAS_OVERLOAD).
    path(
        "api/risk-types/<int:pk>/update/",
        views.risk_type_update_api,
        name="api-risk-type-update",
    ),
    # POST: 위험 유형 정보 수정.
    path(
        "api/risk-types/bulk-delete/",
        views.risk_type_bulk_delete_api,
        name="api-risk-type-bulk-delete",
    ),
    # POST: 선택된 위험 유형 일괄 삭제.
    # ═══════════════════════════════════════════════════════
    # 위험 기준 (알람 단계) 관리
    # ═══════════════════════════════════════════════════════
    path("alarm-levels/", views.alarm_level_list, name="alarm-level-list"),
    # /backoffice/alarm-levels/ → 알람 단계 관리 목록 (정상/주의/경고/위험 등 레벨 정의).
    path(
        "api/alarm-levels/<int:pk>/", views.alarm_level_detail_api, name="api-al-detail"
    ),
    # GET: 알람 단계 1건 상세 반환.
    path(
        "api/alarm-levels/create/", views.alarm_level_create_api, name="api-al-create"
    ),
    # POST: 새 알람 단계 등록 (코드, 이름, 색상, 강도, 우선순위 설정).
    path(
        "api/alarm-levels/<int:pk>/update/",
        views.alarm_level_update_api,
        name="api-al-update",
    ),
    # POST: 알람 단계 정보 수정.
    path(
        "api/alarm-levels/bulk-delete/",
        views.alarm_level_bulk_delete_api,
        name="api-al-bulk-delete",
    ),
    # POST: 선택된 알람 단계 일괄 삭제. is_system=True인 시스템 단계는 삭제 불가.
    # ═══════════════════════════════════════════════════════
    # 임계치 기준 관리
    # ═══════════════════════════════════════════════════════
    path("thresholds/", views.threshold_manage, name="threshold-manage"),
    # /backoffice/thresholds/ → 임계치 기준 관리 페이지 (가스/전력 등 측정 항목별 주의/위험 기준치).
    path(
        "api/threshold-categories/<int:pk>/",
        views.threshold_cat_detail_api,
        name="api-th-cat-detail",
    ),
    # GET: 임계치 분류 1건 상세 + 하위 임계치 항목 목록 반환.
    path(
        "api/threshold-categories/create/",
        views.threshold_cat_create_api,
        name="api-th-cat-create",
    ),
    # POST: 새 임계치 분류 등록 (예: TH_GAS, TH_POWER).
    path(
        "api/threshold-categories/<int:pk>/update/",
        views.threshold_cat_update_api,
        name="api-th-cat-update",
    ),
    # POST: 임계치 분류 정보 수정.
    path("api/thresholds/create/", views.threshold_create_api, name="api-th-create"),
    # POST: 새 임계치 항목 등록 (측정 항목, 단위, 주의값, 위험값 설정).
    path(
        "api/thresholds/<int:pk>/update/",
        views.threshold_update_api,
        name="api-th-update",
    ),
    # POST: 임계치 항목 수정. 여기서 변경하면 실시간 센서 판단 기준도 바뀜.
    path(
        "api/thresholds/bulk-delete/",
        views.threshold_bulk_delete_api,
        name="api-th-bulk-delete",
    ),
    # POST: 선택된 임계치 항목 일괄 삭제.
    path(
        "api/thresholds/bulk-toggle/",
        views.threshold_bulk_toggle_api,
        name="api-th-bulk-toggle",
    ),
    # POST: 선택된 임계치 항목의 is_active(사용 여부) 일괄 변경.
    # ═══════════════════════════════════════════════════════
    # 이벤트 이력 관리 (alerts.Alarm 조회)
    # ═══════════════════════════════════════════════════════
    path("events/", views.event_history, name="event-history"),
    # /backoffice/events/ → 알람 이벤트 이력 조회 페이지 (검색/필터/정렬/페이지네이션).
    path("events/csv/", views.event_history_csv, name="event-history-csv"),
    # /backoffice/events/csv/ → 현재 검색 조건의 이벤트 이력 CSV 다운로드 (Excel 호환).
    path("api/events/<int:pk>/", views.event_detail_api, name="api-event-detail"),
    # GET: 이벤트(알람) 1건 상세 반환 (모달 표시용).
    path(
        "api/events/bulk-read/", views.event_bulk_read_api, name="api-event-bulk-read"
    ),
    # POST: 선택된 이벤트 일괄 읽음 처리. body: {"ids": [...]}.
    # ═══════════════════════════════════════════════════════
    # 알림 정책 관리
    # ═══════════════════════════════════════════════════════
    path("notification-policies/", views.notification_policy_list, name="policy-list"),
    # /backoffice/notification-policies/ → 알림 정책 목록 페이지.
    # 어떤 알람 레벨+위험 분류에서 누구에게 어떤 채널로 알림 보낼지 정책 관리.
    path("api/policies/<int:pk>/", views.policy_detail_api, name="api-policy-detail"),
    # GET: 알림 정책 1건 상세 반환.
    path("api/policies/create/", views.policy_create_api, name="api-policy-create"),
    # POST: 새 알림 정책 등록.
    path(
        "api/policies/<int:pk>/update/",
        views.policy_update_api,
        name="api-policy-update",
    ),
    # POST: 알림 정책 수정.
    path(
        "api/policies/bulk-delete/",
        views.policy_bulk_delete_api,
        name="api-policy-bulk-delete",
    ),
    # POST: 선택된 정책 일괄 삭제.
    path(
        "api/policies/bulk-toggle/",
        views.policy_bulk_toggle_api,
        name="api-policy-bulk-toggle",
    ),
    # POST: 선택된 정책의 is_active(활성 여부) 일괄 변경.
    # ═══════════════════════════════════════════════════════
    # 알림 발송 이력
    # ═══════════════════════════════════════════════════════
    path(
        "notification-logs/", views.notification_log_list, name="notification-log-list"
    ),
    # /backoffice/notification-logs/ → 알림 발송 이력 조회 페이지.
    # 누가 어떤 채널로 발송됐는지, 성공/실패/대기 상태 및 24시간 통계 표시.
    # ═══════════════════════════════════════════════════════
    # 메뉴 관리 (역할별 메뉴 권한)
    # ═══════════════════════════════════════════════════════
    path("menus/", views.menu_management, name="menu-manage"),
    # /backoffice/menus/ → 역할별 메뉴 접근 권한 관리 페이지 (admin 역할의 메뉴 ON/OFF 매트릭스).
    path(
        "api/menu-perms/update/",
        views.menu_perm_update_api,
        name="api-menu-perm-update",
    ),
    # POST: 특정 역할+메뉴의 조회/쓰기 권한 토글. body: {role, menu_code, is_visible, is_writable}.
    # ═══════════════════════════════════════════════════════
    # 설비/장비 관리
    # ═══════════════════════════════════════════════════════
    path("devices/", views.device_list, name="device-list"),
    # /backoffice/devices/ → 장비 목록 페이지 (검색/필터/페이지네이션).
    path("api/devices/<int:pk>/", views.device_detail_api, name="api-device-detail"),
    # GET: 장비 1건 상세 정보 반환.
    path("api/devices/create/", views.device_create_api, name="api-device-create"),
    # POST: 새 장비 등록 (장비 ID, 이름, 센서 타입, 좌표 등).
    path(
        "api/devices/<int:pk>/update/",
        views.device_update_api,
        name="api-device-update",
    ),
    # POST: 장비 정보 수정.
    path(
        "api/devices/bulk-delete/",
        views.device_bulk_delete_api,
        name="api-device-bulk-delete",
    ),
    # POST: 선택된 장비 일괄 삭제.
    path(
        "api/devices/bulk-toggle/",
        views.device_bulk_toggle_api,
        name="api-device-bulk-toggle",
    ),
    # POST: 선택된 장비의 is_active(활성 여부) 일괄 변경.
    path(
        "api/devices/auto-map/",
        views.device_auto_map_geofence_api,
        name="api-device-auto-map",
    ),
    # POST: 모든 장비의 현재 좌표(x, y)를 기반으로 지오펜스를 자동 매핑/해제.
    path(
        "api/devices/csv-upload/",
        views.device_csv_upload_api,
        name="api-device-csv-upload",
    ),
    # POST: CSV 파일로 장비 일괄 등록 또는 upsert. mode=create(기본)/upsert 선택 가능.
    # ═══════════════════════════════════════════════════════
    # 지도 편집 관리
    # ═══════════════════════════════════════════════════════
    path("maps/", views.map_edit, name="map-edit"),
    # /backoffice/maps/ → 지도 + 지오펜스 + 장비 통합 편집 화면.
    # 좌측: 캔버스(지도·지오펜스 폴리곤·장비 마커), 우측: 지오펜스 목록·등록·수정 패널.
    path("api/geofences/<int:pk>/", views.geofence_detail_api, name="api-gf-detail"),
    # GET: 지오펜스 1건 상세 정보 반환.
    path("api/geofences/create/", views.geofence_create_api, name="api-gf-create"),
    # POST: 새 지오펜스 등록 (이름, 구역 유형, 위험 레벨, 폴리곤 좌표 등).
    path(
        "api/geofences/<int:pk>/update/",
        views.geofence_update_api,
        name="api-gf-update",
    ),
    # POST: 지오펜스 정보 수정 (폴리곤 재편집 포함).
    path(
        "api/geofences/<int:pk>/delete/",
        views.geofence_delete_api,
        name="api-gf-delete",
    ),
    # POST: 지오펜스 삭제. 소속 장비의 geofence FK는 SET_NULL로 자동 해제.
    # ═══════════════════════════════════════════════════════
    # 운영 데이터 관리 (보관 정책)
    # ═══════════════════════════════════════════════════════
    path("operations/retention/", views.retention_list, name="retention-list"),
    # /backoffice/operations/retention/ → 데이터 보관 정책 목록 (각 대상별 보관 기간 + 현재 건수).
    path(
        "api/retention/<int:pk>/",
        views.retention_detail_api,
        name="api-retention-detail",
    ),
    # GET: 보관 정책 1건 상세 반환.
    path(
        "api/retention/<int:pk>/update/",
        views.retention_update_api,
        name="api-retention-update",
    ),
    # POST: 보관 기간(retention_days) 및 활성 여부 수정.
    path(
        "api/retention/<int:pk>/run-now/",
        views.retention_run_now_api,
        name="api-retention-run-now",
    ),
    # POST: 특정 데이터 보관 정책 즉시 실행 (기간 초과 데이터 삭제 + 결과 기록).
    # ═══════════════════════════════════════════════════════
    # 공지사항 관리
    # ═══════════════════════════════════════════════════════
    path("notices/", views.notice_list, name="notice-list"),
    # /backoffice/notices/ → 공지사항 목록 페이지 (검색/카테고리 필터/상단 고정 여부).
    path("api/notices/<int:pk>/", views.notice_detail_api, name="api-notice-detail"),
    # GET: 공지사항 1건 상세 반환.
    path("api/notices/create/", views.notice_create_api, name="api-notice-create"),
    # POST: 새 공지사항 등록. send_notify=true 포함 시 등록과 동시에 전체 사용자에게 알림 발송.
    path(
        "api/notices/<int:pk>/update/",
        views.notice_update_api,
        name="api-notice-update",
    ),
    # POST: 공지사항 내용 수정.
    path(
        "api/notices/<int:pk>/dispatch/",
        views.notice_dispatch_api,
        name="api-notice-dispatch",
    ),
    # POST: 기존 공지를 수동으로 사용자에게 알림 발송. body: {"channels": ["app", "realtime"]}.
    path(
        "api/notices/bulk-delete/",
        views.notice_bulk_delete_api,
        name="api-notice-bulk-delete",
    ),
    # POST: 선택된 공지사항 일괄 삭제.
    path(
        "api/notices/bulk-toggle/",
        views.notice_bulk_toggle_api,
        name="api-notice-bulk-toggle",
    ),
    # POST: 선택된 공지의 is_published(게시 여부) 일괄 변경.
    # ═══════════════════════════════════════════════════════
    # v6 — 감사 로그 + 장비 변경 이력
    # ═══════════════════════════════════════════════════════
    path("audit-logs/", views.audit_log_list, name="audit-log-list"),
    # /backoffice/audit-logs/ → 감사 로그 목록 페이지.
    # 백오피스에서 발생한 모든 등록/수정/삭제/로그인 액션을 누가 언제 어떻게 했는지 조회.
    path(
        "api/devices/<int:pk>/history/",
        views.device_history_api,
        name="api-device-history",
    ),
    # GET: 특정 장비의 변경 이력 목록 반환 (최대 50건). 장비 상세 모달의 '변경 이력' 탭 데이터.
]
