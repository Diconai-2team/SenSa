"""
vr_training/urls.py

mysite/urls.py 에서:
    path('vr-training/', include('vr_training.urls'))

최종 경로:
    GET  /vr-training/              — 플레이어 페이지
    POST /vr-training/api/progress/ — 재생 위치 저장
    POST /vr-training/api/complete/ — 완료 처리
"""

# Django URL 패턴 정의에 필요한 path 함수를 불러옴
from django.urls import path

# 같은 앱(vr_training) 폴더의 views.py 모듈 전체를 가져옴
from . import views

# 이 앱의 URL 네임스페이스를 "vr_training"으로 지정
# 템플릿이나 코드에서 {% url 'vr_training:player' %} 형태로 역참조 가능
app_name = "vr_training"

urlpatterns = [
    # GET /vr-training/ → VR 영상 플레이어 페이지를 렌더링하는 뷰 함수 호출
    # 빈 문자열("")이므로 include로 연결된 prefix(/vr-training/) 그대로가 최종 URL
    path("", views.player_page, name="player"),
    # POST /vr-training/api/progress/ → 사용자가 VR 영상을 시청하는 중 재생 위치를 주기적으로 저장하는 API
    # CBV(클래스 기반 뷰)인 VRProgressView를 .as_view()로 함수 형태로 변환해 등록
    path("api/progress/", views.VRProgressView.as_view(), name="progress"),
    # POST /vr-training/api/complete/ → 사용자가 VR 영상을 끝까지 시청했을 때 완료 처리하는 API
    # CBV인 VRCompleteView를 .as_view()로 함수 형태로 변환해 등록
    path("api/complete/", views.VRCompleteView.as_view(), name="complete"),
]
