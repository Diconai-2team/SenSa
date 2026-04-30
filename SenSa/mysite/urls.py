from django.contrib import admin
# Django 관리자 페이지의 URL을 등록하기 위해 admin 사이트를 불러와
from django.urls import path, include
# URL 경로 정의 + 다른 앱의 URL을 포함시키는 헬퍼
from django.conf import settings
# DEBUG 등 환경 설정 참조 — 개발 환경에서만 정적 파일 서빙 추가용
from django.conf.urls.static import static
# 개발 서버에서 정적/미디어 파일을 서빙하기 위한 헬퍼

# 백오피스의 임계치 → FastAPI 동기화 엔드포인트는 /dashboard/api/ 프리픽스 아래
# (InternalAPIKeyMiddleware 가 거기까지를 인식하므로)
from backoffice.views import thresholds_for_fastapi
# ⭐ FastAPI ↔ Django 동기화 단일 진입점 — 백오피스에서 운영자가 변경한 임계치를
#    FastAPI가 가져갈 때 사용. InternalAPIKeyMiddleware의 화이트리스트와 정확히 일치하는 경로


urlpatterns = [
    path('admin/', admin.site.urls),
    # 'admin/' 경로 — Django 기본 관리자 페이지 (모든 앱의 admin.py 통합 노출)

    # === accounts (인증) ===
    path('', include('accounts.urls')),
    # 빈 경로(루트)에 accounts.urls 포함 — 로그인/회원가입/내정보가 사이트 루트 수준
    # 즉 /, /accounts/login/, /home/ 등이 accounts 앱에서 처리됨

    # === dashboard (통합 화면) ===
    path('dashboard/', include('dashboard.urls')),        # 'monitor.urls' → 'dashboard.urls'
    # 'dashboard/' 경로에 dashboard 앱의 URL 포함 — 관제 지도 페이지 + 알람 목록 페이지
    path('dashboard/api/', include('devices.urls')),      # 'monitor/api/' → 'dashboard/api/'
    # 'dashboard/api/' 하위에 devices 앱의 URL 포함 — 센서 CRUD + sensor-data 수신
    # ⭐ 같은 prefix(dashboard/api/)에 4개 앱(devices/geofence/alerts/workers)을 모음
    #    클라이언트(SVG 대시보드)에서 한 base URL로 모든 데이터 호출 가능
    path('dashboard/api/', include('geofence.urls')),
    # 'dashboard/api/geofence/' — 지오펜스 CRUD
    path('dashboard/api/', include('alerts.urls')),
    # 'dashboard/api/alarm/' — 알람 조회/통계/읽음 처리
    path('dashboard/api/', include('workers.urls')),     # ← Worker API 추가
    # 'dashboard/api/worker/', 'dashboard/api/worker-location/' — 작업자 + 위치 시계열

    # === FastAPI ↔ Django 임계치 동기화 (internal) ===
    path('dashboard/api/thresholds/', thresholds_for_fastapi, name='thresholds-sync'),
    # FastAPI가 백오피스 임계치 가져갈 때 호출하는 경로 — InternalAPIKeyMiddleware 보호 대상
    # ViewSet 아닌 함수형 뷰 — 단일 엔드포인트라 router 불필요

    path('safety/', include('safety.urls')),    # ← 추가
    # 'safety/' — 안전 체크리스트 (dashboard.map_view가 try/except로 참조)
    path('vr-training/', include('vr_training.urls')),    # ← 추가
    # 'vr-training/' — VR 안전 교육 로그 (dashboard.map_view가 try/except로 참조)
    path('workers/', include('workers.page_urls')),         # ← 이 줄 추가
    # ⭐ workers 앱은 URL 두 곳에서 등록됨
    #   - /dashboard/api/worker/ (위에서 등록한 DRF API)
    #   - /workers/ (Phase 4A 페이지 + 전용 API)
    # 같은 앱이지만 책임 분리 (대시보드용 API vs 작업자 현황 페이지)

    # === 백오피스 (슈퍼관리자 채널) ===
    path('backoffice/', include('backoffice.urls', namespace='backoffice')),
    # 'backoffice/' — 슈퍼관리자 전용 백오피스 (조직/임계치/사용자 관리)
    # namespace='backoffice' — reverse('backoffice:landing') 형태로 URL 생성
]

if settings.DEBUG:
    # DEBUG=True 환경에서만 추가 — 운영에선 Nginx 등이 정적 파일 서빙
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # 개발 서버가 STATIC_ROOT의 파일을 STATIC_URL 경로로 서빙
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # 업로드된 평면도 이미지(MapImage.image) 등을 개발 서버에서 서빙