"""
safety/urls.py — 안전 확인 앱 URL

mysite/urls.py 에서:
    path('safety/', include('safety.urls'))

최종 경로:
    GET  /safety/checklist/         — 페이지
    POST /safety/checklist/submit/  — 제출 API
"""

# Django URL 패턴 정의에 필요한 path 함수를 불러옴
from django.urls import path

# 같은 앱(safety) 폴더의 views.py 모듈 전체를 가져옴
from . import views

# 이 앱의 URL 네임스페이스를 "safety"로 지정
# 템플릿이나 코드에서 {% url 'safety:checklist' %} 형태로 역참조 가능
app_name = "safety"

urlpatterns = [
    # GET /safety/checklist/ → 안전 확인 체크리스트 페이지를 렌더링하는 뷰 함수 호출
    # name="checklist"으로 URL 이름을 지정해 템플릿/리다이렉트에서 재사용 가능
    path("checklist/", views.checklist_page, name="checklist"),
    path(
        # POST /safety/checklist/submit/ → 사용자가 체크리스트를 제출할 때 호출되는 API 엔드포인트
        "checklist/submit/",
        # ChecklistSubmitView는 클래스 기반 뷰(CBV)이므로 .as_view()로 함수 형태로 변환해 등록
        views.ChecklistSubmitView.as_view(),
        # name="checklist-submit"으로 URL 이름 지정해 역참조 시 사용
        name="checklist-submit",
    ),
]
