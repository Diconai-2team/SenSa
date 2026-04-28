from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'device', views.DeviceViewSet, basename='device')

urlpatterns = [
    path('', include(router.urls)),
    path('sensor-data/', views.SensorDataView.as_view(), name='sensor-data'),
]
