"""
monitor 앱 URL 설정

- 페이지: 관제 지도 화면
- API: 공장 평면도 CRUD + 지오펜스 내부 판별
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'map', views.MapImageViewSet, basename='map')

urlpatterns = [
    # === 페이지 ===
    path('', views.map_view, name='dashboard'),

    # === API ===
    path('api/', include(router.urls)),
    path('api/check-geofence/', views.CheckGeofenceView.as_view(), name='check-geofence'),
]
