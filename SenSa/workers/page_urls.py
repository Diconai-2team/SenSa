"""
workers/page_urls.py — 작업자 현황 페이지 전용 URL (Phase 4A 신규)

mysite/urls.py:
  path('workers/', include('workers.page_urls'))

최종 URL:
  GET  /workers/                — 작업자 현황 목록 페이지
  GET  /workers/api/list/       — 목록 + 요약 데이터 (JSON, 세션 인증)
  POST /workers/api/notify/     — 푸시 알림 전송 (더미)
"""
# ⭐ Phase 4A에서 기존 urls.py(대시보드용 DRF API)와 분리한 이유:
#    1. 페이지 응집도 — 작업자 현황 페이지 관련 URL을 한 파일에
#    2. 인증 정책 분리 — page_urls는 세션 인증, urls.py는 DRF 표준
#    3. 책임 분리 — 향후 4B의 폴링/WS 전환 시 이 파일만 수정

from django.urls import path
# 단순 path 등록만 사용 — Router 안 씀 (ViewSet 아닌 APIView 기반이라)
from . import views


app_name = 'workers'
# URL namespace — reverse('workers:list') 형태로 사용
# ⚠️ urls.py(대시보드용)에는 app_name 없음 — 기존 코드 호환을 위해 namespace 미적용


urlpatterns = [
    path('',            views.worker_list_page,              name='list'),
    # 빈 경로('')는 prefix 'workers/' 자체에 매핑 — GET /workers/ → 목록 페이지 HTML
    # name='list' — reverse('workers:list')로 URL 생성 가능
    path('api/list/',   views.WorkerListDataView.as_view(),  name='api-list-data'),
    # 'api/list/' 경로 — JSON 데이터 공급 (목록 + 요약)
    # 페이지 초기 렌더 후 JS가 fetch로 호출하는 구조
    path('api/notify/', views.WorkerNotifyView.as_view(),    name='api-notify'),
    # 'api/notify/' 경로 — POST로 푸시 알림 전송 (Phase 4A는 DB 저장까지만)
]