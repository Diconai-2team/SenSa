from django.urls import path, include
# Django에서 URL 경로를 정의하는 path 함수와, 다른 URL 설정을 포함시키는 include 함수를 불러와
from rest_framework.routers import DefaultRouter
# DRF의 DefaultRouter를 불러와 (ViewSet을 자동으로 URL에 등록해주는 라우터)
from . import views
# 같은 앱(geofence) 안의 views 모듈을 불러와 — GeoFenceViewSet 참조용


router = DefaultRouter()
# DefaultRouter 인스턴스를 생성할게 (ViewSet을 URL에 자동 등록하기 위한 라우터)
router.register(r'geofence', views.GeoFenceViewSet, basename='geofence')
# 'geofence/' 경로에 GeoFenceViewSet을 등록할게 (ModelViewSet이라 CRUD 5종 자동 생성)
# 자동 생성되는 URL:
#   GET    geofence/         → list (활성 지오펜스 목록)
#   POST   geofence/         → create (새 지오펜스 등록)
#   GET    geofence/{pk}/    → retrieve (단일 조회)
#   PUT    geofence/{pk}/    → update (전체 갱신)
#   PATCH  geofence/{pk}/    → partial_update (부분 갱신)
#   DELETE geofence/{pk}/    → destroy (소프트 삭제 — is_active=False)


urlpatterns = [
    path('', include(router.urls)),
    # 빈 경로 하위에 router에 등록된 모든 URL을 포함시킬게
    # 실제로는 dashboard/urls.py에서 'api/' prefix를 붙여 'api/geofence/'로 노출됨
]
# ⚠️ 지오펜스 편집 페이지(HTML)가 없음 — polygon 좌표를 어떻게 입력하는지 코드만으론 불명확
#    별도 dashboard에서 SVG 클릭으로 polygon 편집하는 UI가 있을 것으로 추정