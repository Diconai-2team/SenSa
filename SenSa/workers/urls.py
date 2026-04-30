"""
workers/urls.py — 대시보드용 DRF API (기존 유지)

mysite/urls.py:
  path('dashboard/api/', include('workers.urls'))

최종 URL (변경 없음):
  /dashboard/api/worker/
  /dashboard/api/worker/{id}/
  /dashboard/api/worker/{id}/latest/
  /dashboard/api/worker-location/

Phase 4A 의 페이지/알림 API 는 workers.page_urls 에 분리.
"""
# ⭐ workers 앱은 URL 파일이 2개 — 책임 분리 패턴
#    urls.py: 기존 대시보드 DRF API (Phase 1~3 누적)
#    page_urls.py: Phase 4A 작업자 현황 페이지 (위에 정리됨)

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views


router = DefaultRouter()
# ViewSet을 URL에 자동 등록하는 라우터
router.register(r'worker', views.WorkerViewSet, basename='worker')
# 'worker/' 경로에 WorkerViewSet 등록 (CRUD + latest 액션 자동 생성)
# 자동 URL:
#   GET    worker/              → list
#   POST   worker/              → create
#   GET    worker/{id}/         → retrieve
#   PUT    worker/{id}/         → update
#   PATCH  worker/{id}/         → partial_update
#   DELETE worker/{id}/         → destroy (소프트 삭제로 오버라이드됨)
#   GET    worker/{id}/latest/  → @action latest (최신 위치 1건 조회)
router.register(r'worker-location', views.WorkerLocationViewSet, basename='worker-location')
# 'worker-location/' 경로에 WorkerLocationViewSet 등록 (위치 시계열 CRUD)
# POST 시 perform_create가 last_seen_at 자동 갱신 + WebSocket 푸시


urlpatterns = [
    path('', include(router.urls)),
    # router의 모든 URL을 빈 경로 하위에 포함
    # 외부 노출 경로는 mysite/urls.py에서 'dashboard/api/' prefix로 결정됨
]
