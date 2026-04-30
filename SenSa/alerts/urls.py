from django.urls import path, include
# Django에서 URL 경로를 정의하는 path 함수와, 다른 URL 설정을 포함시키는 include 함수를 불러와
# include는 router.urls처럼 여러 URL 묶음을 한 번에 등록할 때 사용해
from rest_framework.routers import DefaultRouter
# DRF의 DefaultRouter를 불러와 (ViewSet을 자동으로 URL에 등록해주는 라우터)
# list/retrieve/create/update/destroy + 커스텀 @action들의 URL을 자동 생성해줘
from . import views
# 같은 앱(alerts) 안의 views 모듈을 불러와 — AlarmViewSet 참조용


router = DefaultRouter()
# DefaultRouter 인스턴스를 생성할게 (ViewSet을 URL에 자동 등록하기 위한 라우터)
# SimpleRouter와 달리 API root 페이지(/)도 자동 생성해 — 개발 시 편의성 ↑
router.register(r'alarm', views.AlarmViewSet, basename='alarm')
# 'alarm/' 경로에 AlarmViewSet을 등록할게
# basename='alarm' — reverse() 호출 시 'alarm-list', 'alarm-detail', 'alarm-stats' 형태 사용
# 자동 생성되는 URL:
#   GET    alarm/              → list (queryset 조회)
#   GET    alarm/{pk}/         → retrieve (단일 조회)
#   GET    alarm/stats/        → @action stats (24h 통계)
#   PATCH  alarm/{pk}/read/    → @action read (개별 읽음 처리)
#   PATCH  alarm/read_all/     → @action read_all (전체 읽음 처리)


urlpatterns = [
    path('', include(router.urls)),
    # 빈 경로('') 하위에 router에 등록된 모든 URL을 포함시킬게
    # 실제로는 dashboard/urls.py에서 'api/' prefix를 붙여 'api/alarm/'으로 노출됨
    # 즉 최종 URL은 '/dashboard/api/alarm/...' 형태
]
# ⚠️ 리뷰: alarm_list_view(HTML 페이지)는 dashboard/urls.py에 직접 등록되어 있음
#         alerts 앱 응집도 측면에서 여기로 이동하는 게 더 깔끔할 수 있음