"""
vr_training/urls.py

mysite/urls.py 에서:
    path('vr-training/', include('vr_training.urls'))

최종 경로:
    GET  /vr-training/              — 플레이어 페이지
    POST /vr-training/api/progress/ — 재생 위치 저장
    POST /vr-training/api/complete/ — 완료 처리
"""

from django.urls import path

from . import views

app_name = "vr_training"

urlpatterns = [
    path("", views.player_page, name="player"),
    path("api/progress/", views.VRProgressView.as_view(), name="progress"),
    path("api/complete/", views.VRCompleteView.as_view(), name="complete"),
]
