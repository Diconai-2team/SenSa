"""
geofence/scenario_views.py — 시나리오 API (격리 + 운영).

[격리 시나리오 API — CLI/회귀 보조용, 패널에서 안 씀]
    GET  /dashboard/api/scenarios/list/
    POST /dashboard/api/scenarios/run/<name>/
    POST /dashboard/api/scenarios/cleanup/

[운영 시나리오 API — 대시보드 패널 전용]
    GET  /dashboard/api/scenarios/op/list/
    POST /dashboard/api/scenarios/op/run/<name>/
    POST /dashboard/api/scenarios/op/cleanup/
"""
import traceback

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated


# 격리 시나리오 시연 zone 유지 시간 (초). 운영 시나리오는 각자 ZONE_TTL_SEC.
DEMO_TTL_SECONDS = 60


# ════════════════════════════════════════════════════════════════
# 격리 시나리오 API (D-1/D-2 — CLI 동반 보조용)
# ════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_scenarios_api(request):
    from geofence.scenarios import list_scenarios
    return JsonResponse({
        'status': 'success',
        'scenarios': list_scenarios(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_scenario_api(request, name):
    from geofence.scenarios import get_scenario

    try:
        cls = get_scenario(name)
    except KeyError:
        return JsonResponse({
            'status': 'error',
            'error': f"unknown scenario '{name}'",
        }, status=400)

    try:
        scenario = cls()
        result = scenario.execute(
            verify=False, keep=True, demo_ttl_seconds=DEMO_TTL_SECONDS,
        )
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': f"{type(e).__name__}: {e}",
            'trace': traceback.format_exc(),
        }, status=500)

    return JsonResponse({
        'status':            'success',
        'name':              name,
        'zone_ids':          result.get('kept_zone_ids', []),
        'device_ids':        result.get('kept_device_ids', []),
        'actual':            result.get('actual', {}),
        'demo_ttl_seconds':  DEMO_TTL_SECONDS,
        'expires_at':        result.get('expires_at'),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cleanup_scenarios_api(request):
    from devices.models import Device, SensorData
    from geofence.models import GeoFence

    zone_count = GeoFence.objects.filter(name__startswith='[시나리오]').count()
    GeoFence.objects.filter(name__startswith='[시나리오]').delete()

    dev_qs = Device.objects.filter(device_id__startswith='sensa_scenario_')
    dev_count = dev_qs.count()
    dev_qs.update(is_active=False)
    SensorData.objects.filter(
        device__device_id__startswith='sensa_scenario_',
    ).delete()
    try:
        dev_qs.delete()
    except Exception as e:
        return JsonResponse({
            'status': 'partial',
            'cleaned_zones': zone_count,
            'cleaned_devices': 0,
            'error': f"device 삭제 실패 (비활성화는 OK): {e}",
        })

    return JsonResponse({
        'status': 'success',
        'cleaned_zones': zone_count,
        'cleaned_devices': dev_count,
    })


# ════════════════════════════════════════════════════════════════
# 운영 시나리오 API (Phase Demo v2 — 대시보드 패널 전용)
# ════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_op_scenarios_api(request):
    """운영 시나리오 목록 (패널 초기화용)."""
    from geofence.scenarios import list_op_scenarios
    return JsonResponse({
        'status': 'success',
        'scenarios': list_op_scenarios(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_op_scenario_api(request, name):
    """운영 시나리오 실행 — 운영 sensor 에 spike 주입 + zone 생성."""
    from geofence.scenarios import get_op_scenario

    try:
        cls = get_op_scenario(name)
    except KeyError:
        return JsonResponse({
            'status': 'error',
            'error': f"unknown op scenario '{name}'",
        }, status=400)

    try:
        scenario = cls()
        result = scenario.execute()
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': f"{type(e).__name__}: {e}",
            'trace': traceback.format_exc(),
        }, status=500)

    if result.get('status') != 'success':
        return JsonResponse(result, status=500)

    return JsonResponse(result)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cleanup_op_scenarios_api(request):
    """운영 시나리오 잔존물 일괄 정리.

    - GeoFence: trigger_source 'scenario_op_*' + name '[시나리오] *' 모두
    - SensorData: 시간이 흐르며 LOOKBACK (5분) 빠지며 자연 회복.
                  명시 삭제 안 함 (운영 caution 데이터와 구분 어려움).
    """
    from geofence.scenarios import cleanup_all_operational_scenarios

    try:
        result = cleanup_all_operational_scenarios()
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': f"{type(e).__name__}: {e}",
        }, status=500)

    return JsonResponse({
        'status': 'success',
        **result,
    })
