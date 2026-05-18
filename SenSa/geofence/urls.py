from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import scenario_views

router = DefaultRouter()
router.register(r'geofence', views.GeoFenceViewSet, basename='geofence')

urlpatterns = [
    path('', include(router.urls)),

    # ─── Phase D 격리 시나리오 API (CLI 동반 보조용) ────────────
    # /dashboard/api/scenarios/list/
    # /dashboard/api/scenarios/run/<name>/
    # /dashboard/api/scenarios/cleanup/
    path(
        'scenarios/list/',
        scenario_views.list_scenarios_api,
        name='scenario-list',
    ),
    path(
        'scenarios/run/<str:name>/',
        scenario_views.run_scenario_api,
        name='scenario-run',
    ),
    path(
        'scenarios/cleanup/',
        scenario_views.cleanup_scenarios_api,
        name='scenario-cleanup',
    ),

    # ─── Phase Demo v2 운영 시나리오 API (대시보드 패널 전용) ────
    # /dashboard/api/scenarios/op/list/
    # /dashboard/api/scenarios/op/run/<name>/
    # /dashboard/api/scenarios/op/cleanup/
    path(
        'scenarios/op/list/',
        scenario_views.list_op_scenarios_api,
        name='scenario-op-list',
    ),
    path(
        'scenarios/op/run/<str:name>/',
        scenario_views.run_op_scenario_api,
        name='scenario-op-run',
    ),
    path(
        'scenarios/op/cleanup/',
        scenario_views.cleanup_op_scenarios_api,
        name='scenario-op-cleanup',
    ),
]
