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
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'worker', views.WorkerViewSet, basename='worker')
router.register(r'worker-location', views.WorkerLocationViewSet, basename='worker-location')

urlpatterns = [
    path('', include(router.urls)),
]