"""
alerts/services.py
알람 생성 로직 — 지오펜스 진입, 센서 이상, 복합 위험 알람 생성
"""
from geofence.models import GeoFence
from geofence.services import point_in_polygon
from .models import Alarm


def check_worker_in_geofences(worker_id: str, worker_name: str,
                               x: float, y: float) -> list:
    """
    작업자 좌표(x, y)가 어떤 지오펜스 안에 있는지 확인.
    진입이 감지된 지오펜스마다 알람을 생성하고 목록으로 반환.
    """
    results = []
    fences = GeoFence.objects.filter(is_active=True)

    for fence in fences:
        if not fence.polygon or len(fence.polygon) < 3:
            continue

        if point_in_polygon(x, y, fence.polygon):
            level = _zone_to_alarm_level(fence.zone_type)
            msg = f"{worker_name}이(가) [{fence.name}]에 진입했습니다. (zone: {fence.zone_type})"

            alarm = Alarm.objects.create(
                alarm_type='geofence_enter',
                alarm_level=level,
                worker_id=worker_id,
                worker_name=worker_name,
                worker_x=x,
                worker_y=y,
                geofence=fence,
                message=msg,
            )

            results.append({
                "geofence_id": fence.id,
                "geofence_name": fence.name,
                "zone_type": fence.zone_type,
                "alarm_id": alarm.id,
                "alarm_level": level,
                "message": msg,
            })

    return results


def create_sensor_alarm(device_id: str, sensor_type: str,
                        status: str, detail: str = '') -> dict | None:
    """
    센서 상태가 caution 또는 danger일 때 알람 생성.
    normal이면 None 반환.
    """
    if status == 'normal':
        return None

    alarm_type = 'sensor_caution' if status == 'caution' else 'sensor_danger'
    alarm_level = 'caution' if status == 'caution' else 'danger'
    msg = f"센서 [{device_id}] {status.upper()} 상태 감지. {detail}"

    alarm = Alarm.objects.create(
        alarm_type=alarm_type,
        alarm_level=alarm_level,
        device_id=device_id,
        sensor_type=sensor_type,
        message=msg,
    )

    return {
        "alarm_id": alarm.id,
        "alarm_level": alarm_level,
        "alarm_type": alarm_type,
        "message": msg,
    }


def create_combined_alarm(worker_id: str, worker_name: str,
                          geofence: GeoFence, device_id: str,
                          sensor_status: str) -> dict:
    """
    작업자가 지오펜스 안에 있는데 + 해당 구역 센서도 위험 수치일 때.
    가장 높은 수준의 알람(critical) 생성.
    """
    msg = (
        f"[복합위험] {worker_name}이(가) [{geofence.name}]에 있는 상태에서 "
        f"센서 [{device_id}] {sensor_status.upper()} 수치 감지!"
    )

    alarm = Alarm.objects.create(
        alarm_type='combined',
        alarm_level='critical',
        worker_id=worker_id,
        worker_name=worker_name,
        geofence=geofence,
        device_id=device_id,
        message=msg,
    )

    return {
        "alarm_id": alarm.id,
        "alarm_level": "critical",
        "alarm_type": "combined",
        "message": msg,
    }


def _zone_to_alarm_level(zone_type: str) -> str:
    return {
        'danger': 'danger',
        'caution': 'caution',
        'restricted': 'critical',
    }.get(zone_type, 'caution')
