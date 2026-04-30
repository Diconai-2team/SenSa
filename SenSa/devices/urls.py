from django.urls import path, include
# Django에서 URL 경로를 정의하는 path 함수와, 다른 URL 설정을 포함시키는 include 함수를 불러와
from rest_framework.routers import DefaultRouter
# DRF의 DefaultRouter를 불러와 (ViewSet을 자동으로 URL에 등록해주는 라우터)
from . import views
# 같은 앱(devices) 안의 views 모듈을 불러와 — DeviceViewSet, SensorDataView 참조용


router = DefaultRouter()
# DefaultRouter 인스턴스를 생성할게 (ViewSet을 URL에 자동 등록하기 위한 라우터)
router.register(r'device', views.DeviceViewSet, basename='device')
# 'device/' 경로에 DeviceViewSet을 등록할게 (ModelViewSet이라 CRUD 5종 자동 생성)
# 자동 생성되는 URL:
#   GET    device/         → list (Step 1A: ?sensor_type=gas|power 필터 지원)
#   POST   device/         → create
#   GET    device/{pk}/    → retrieve
#   PUT    device/{pk}/    → update (전체 갱신)
#   PATCH  device/{pk}/    → partial_update (부분 갱신)
#   DELETE device/{pk}/    → destroy


urlpatterns = [
    path('', include(router.urls)),
    # 빈 경로 하위에 router에 등록된 모든 URL을 포함시킬게
    # 실제로는 dashboard/urls.py에서 'api/' prefix를 붙여 'api/device/...'로 노출됨
    path('sensor-data/', views.SensorDataView.as_view(), name='sensor-data'),
    # 'sensor-data/' 경로로 접근하면 SensorDataView 클래스형 뷰를 실행할게
    # GET — 특정 센서의 측정 히스토리 조회 (?device_id=...&limit=20)
    # POST — gas/power 측정값 수신 + 판정 + 저장 + WebSocket push (시스템 핵심 진입점)
    # name='sensor-data' — reverse() 호출 시 사용
    # ⚠️ ViewSet과 별도로 APIView를 둔 이유: SensorData는 standard CRUD가 아닌
    #    "수신→판정→저장→push" 통합 워크플로우를 제공하므로 ModelViewSet에 안 맞음
]
