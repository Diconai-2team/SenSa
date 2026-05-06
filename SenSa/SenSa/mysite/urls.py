from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# 백오피스의 임계치 → FastAPI 동기화 엔드포인트는 /dashboard/api/ 프리픽스 아래
# (InternalAPIKeyMiddleware 가 거기까지를 인식하므로)
from backoffice.views import thresholds_for_fastapi

urlpatterns = [
    path('admin/', admin.site.urls),

    # === accounts (인증) ===
    path('', include('accounts.urls')),

    # === dashboard (통합 화면) ===
    path('dashboard/', include('dashboard.urls')),        # 'monitor.urls' → 'dashboard.urls'
    path('dashboard/api/', include('devices.urls')),      # 'monitor/api/' → 'dashboard/api/'
    path('dashboard/api/', include('geofence.urls')),
    path('dashboard/api/', include('alerts.urls')),
    path('dashboard/api/', include('workers.urls')),     # ← Worker API 추가

    # === FastAPI ↔ Django 임계치 동기화 (internal) ===
    path('dashboard/api/thresholds/', thresholds_for_fastapi, name='thresholds-sync'),

    path('safety/', include('safety.urls')),    # ← 추가
    path('vr-training/', include('vr_training.urls')),    # ← 추가
    path('workers/', include('workers.page_urls')),         # ← 이 줄 추가

    # === 백오피스 (슈퍼관리자 채널) ===
    path('backoffice/', include('backoffice.urls', namespace='backoffice')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
