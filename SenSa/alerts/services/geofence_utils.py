"""
alerts/services/geofence_utils.py — 좌표/장비 ID → 소속 지오펜스 조회.

worker_evaluator (좌표 기반 다중 매칭) 와 sensor_evaluator (장비 ID 기반 단일 매칭)
둘 다 사용. 알람 도메인의 지오펜스 lookup 단일 출처.
"""
from geofence.models import GeoFence
from geofence.services import point_in_polygon


def _find_containing_geofences(x: float, y: float) -> list:
    """작업자 좌표가 속한 활성 지오펜스 목록."""
    result = []
    for fence in GeoFence.objects.filter(is_active=True):
        if not fence.polygon or len(fence.polygon) < 3:
            continue
        if point_in_polygon(x, y, fence.polygon):
            result.append(fence)
    return result


def _find_sensor_geofence(device_id: str):
    """
    센서 device_id 로 속한 지오펜스 반환. 없으면 None.

    판정 순서:
      1순위: Device.geofence FK (seed_data 자동 할당 결과)
      2순위: 좌표 기반 point_in_polygon (FK 미지정 센서용 fallback)
    """
    try:
        from devices.models import Device   # 순환 import 방지
    except Exception:
        return None

    try:
        device = Device.objects.select_related('geofence').get(device_id=device_id)
    except Device.DoesNotExist:
        return None

    # 1순위: 명시적 FK
    if device.geofence and device.geofence.is_active:
        return device.geofence

    # 2순위: 좌표 기반
    for fence in GeoFence.objects.filter(is_active=True):
        if fence.polygon and len(fence.polygon) >= 3:
            if point_in_polygon(device.x, device.y, fence.polygon):
                return fence
    return None
