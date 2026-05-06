from django.urls import path
from .views import SensorDataListCreateView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("api/sensors/", SensorDataListCreateView.as_view(), name="sensor-list-create"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
