"""
workers/urls.py — 작업자 API URL 라우팅

mysite/urls.py에서 이렇게 포함:
  path('dashboard/api/', include('workers.urls'))

그러면 최종 URL:
  /dashboard/api/worker/
  /dashboard/api/worker/{id}/
  /dashboard/api/worker/{id}/latest/
  /dashboard/api/worker-location/
  /dashboard/api/worker-location/{id}/
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ── DefaultRouter ──
# ViewSet의 메서드들을 자동으로 URL 패턴에 매핑해줌
#
# router.register('worker', WorkerViewSet) 하면 자동 생성:
#   worker/           → list (GET), create (POST)
#   worker/{pk}/      → retrieve (GET), update (PUT/PATCH), destroy (DELETE)
#   worker/{pk}/latest/ → @action으로 추가한 커스텀 엔드포인트
router = DefaultRouter()

# ── register(접두사, ViewSet, basename) ──
# 접두사: URL 경로 (r'worker' → /worker/)
# basename: URL 이름의 접두사
#   reverse('worker-list')   → /dashboard/api/worker/
#   reverse('worker-detail') → /dashboard/api/worker/1/
router.register(r'worker', views.WorkerViewSet, basename='worker')
router.register(r'worker-location', views.WorkerLocationViewSet, basename='worker-location')

urlpatterns = [
    # router.urls에 위에서 자동 생성된 URL 패턴들이 들어있음
    path('', include(router.urls)),
]