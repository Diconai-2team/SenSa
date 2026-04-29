from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    # === accounts (인증) ===
    path("", include("accounts.urls")),
    # === dashboard (통합 화면) ===
    path("dashboard/", include("dashboard.urls")),  # 'monitor.urls' → 'dashboard.urls'
    path(
        "dashboard/api/", include("devices.urls")
    ),  # 'monitor/api/' → 'dashboard/api/'
    path("dashboard/api/", include("geofence.urls")),
    path("dashboard/api/", include("alerts.urls")),
    path("dashboard/api/", include("workers.urls")),  # ← Worker API 추가
    path("safety/", include("safety.urls")),  # ← 추가
    path("vr-training/", include("vr_training.urls")),  # ← 추가
    path("workers/", include("workers.page_urls")),  # ← 이 줄 추가
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
