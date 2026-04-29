"""
workers/page_urls.py — 작업자 현황 페이지 전용 URL (Phase 4A 신규)

mysite/urls.py:
  path('workers/', include('workers.page_urls'))

최종 URL:
  GET  /workers/                — 작업자 현황 목록 페이지
  GET  /workers/api/list/       — 목록 + 요약 데이터 (JSON, 세션 인증)
  POST /workers/api/notify/     — 푸시 알림 전송 (더미)
"""

from django.urls import path
from . import views

app_name = "workers"

urlpatterns = [
    path("", views.worker_list_page, name="list"),
    path("api/list/", views.WorkerListDataView.as_view(), name="api-list-data"),
    path("api/notify/", views.WorkerNotifyView.as_view(), name="api-notify"),
]
