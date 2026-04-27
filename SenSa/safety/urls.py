"""
safety/urls.py — 안전 확인 앱 URL

mysite/urls.py 에서:
    path('safety/', include('safety.urls'))

최종 경로:
    GET  /safety/checklist/         — 페이지
    POST /safety/checklist/submit/  — 제출 API
"""
from django.urls import path

from . import views

app_name = 'safety'

urlpatterns = [
    path('checklist/', views.checklist_page, name='checklist'),
    path('checklist/submit/', views.ChecklistSubmitView.as_view(), name='checklist-submit'),
]