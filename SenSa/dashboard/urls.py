"""
dashboard 앱 URL 설정
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views
from alerts.views import alarm_list_view
from alerts.views import AlarmViewSet, AIPredictionViewSet

router = DefaultRouter()
router.register(r'map',            views.MapImageViewSet,  basename='map')
router.register(r'alarm',          AlarmViewSet,           basename='alarm')
router.register(r'ai-predictions', AIPredictionViewSet,    basename='ai-predictions')

urlpatterns = [
    path('',        views.map_view,      name='dashboard'),
    path('alarms/', alarm_list_view,     name='alarm-list'),
    path('api/',    include(router.urls)),
    path('api/check-geofence/', views.CheckGeofenceView.as_view(), name='check-geofence'),
    path('api/ai-forecast/',    views.AIForecastView.as_view(),    name='ai-forecast'),  # G1
    # [P2 STEP 7] Celery task 상태 추적 API
    path('api/task-status/<str:task_id>/', views.TaskStatusView.as_view(), name='task-status'),
]
