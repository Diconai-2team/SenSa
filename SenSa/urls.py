from django.urls import path
from .views import SensorDataListCreateView

urlpatterns = [
    path('api/sensors/', SensorDataListCreateView.as_view(), name='sensor-list-create'),
]