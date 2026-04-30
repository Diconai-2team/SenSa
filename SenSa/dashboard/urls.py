"""
dashboard 앱 URL 설정

- 페이지: 관제 지도 화면, 알람 목록
- API: 공장 평면도 CRUD + 지오펜스 내부 판별
"""

from django.urls import path, include
# Django에서 URL 경로를 정의하는 path 함수와, 다른 URL 설정을 포함시키는 include 함수를 불러와
from rest_framework.routers import DefaultRouter
# DRF의 DefaultRouter를 불러와 (ViewSet을 자동으로 URL에 등록해주는 라우터)

from . import views
# 같은 앱(dashboard) 안의 views 모듈을 불러와
from alerts.views import alarm_list_view   # ← alarm_list_view만 import
# alerts 앱의 alarm_list_view 함수를 불러와 — 알람 목록 페이지를 dashboard 하위로 노출하기 위함
# ⚠️ 책임 위치 불일치 — alerts 앱의 페이지를 dashboard urls.py에서 등록
#    응집도 측면에선 alerts 앱이 자기 페이지 URL을 직접 노출하는 게 더 깔끔


router = DefaultRouter()
# DefaultRouter 인스턴스를 생성할게 (ViewSet을 URL에 자동 등록하기 위한 라우터)
router.register(r'map', views.MapImageViewSet, basename='map')
# 'api/map/' 경로에 MapImageViewSet을 등록할게 (공장 평면도 CRUD API 자동 생성)
# 자동 생성되는 URL:
#   GET    api/map/           → list (전체 평면도 목록)
#   POST   api/map/           → create (새 평면도 업로드 + 기존 비활성화)
#   GET    api/map/{id}/      → retrieve
#   PUT/PATCH api/map/{id}/   → update
#   DELETE api/map/{id}/      → destroy
#   GET    api/map/current/   → @action current (현재 활성 평면도만)


urlpatterns = [
    # === 페이지 ===
    path('', views.map_view, name='dashboard'),
    # 빈 경로 — 'dashboard/' prefix 자체에 매핑 → GET /dashboard/ → 관제 지도 페이지 (시스템 메인)
    path('alarms/', alarm_list_view, name='alarm-list'),    # ← 추가
    # 'alarms/' 경로 — alerts 앱의 alarm_list_view 호출 (알람 상세 목록 페이지)

    # === API ===
    path('api/', include(router.urls)),
    # 'api/' prefix 하위에 router의 모든 URL 포함 → /dashboard/api/map/...
    path('api/check-geofence/', views.CheckGeofenceView.as_view(), name='check-geofence'),
    # 'api/check-geofence/' 경로 — 시스템 핵심 진입점 (작업자+센서 상태 전이 알람 발행)
    # 클라이언트(브라우저 시뮬 또는 외부 디바이스)가 주기적으로 POST 호출
]
