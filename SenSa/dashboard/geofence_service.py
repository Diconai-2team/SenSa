"""
geofence_service.py
지오펜스 내부 판별 + 알람 생성 로직
--- Ray Casting 알고리즘 ---
점(x, y)에서 오른쪽으로 무한히 뻗는 광선이
polygon의 변(edge)과 홀수 번 교차하면 내부, 짝수 번이면 외부.
예시:
  polygon = [[0,0],[100,0],[100,100],[0,100]]  (정사각형)
  점 (50, 50) → 내부
  점 (150, 50) → 외부
"""

from .models import GeoFence, Alarm


# ════════════════════════════════════════════
# 1. Ray Casting — 점이 polygon 안에 있는지 판별
# ════════════════════════════════════════════

def point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """
    polygon: [[x1,y1], [x2,y2], ...] 형태의 꼭짓점 배열
    반환: True(내부) / False(외부)
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1  # 이전 꼭짓점 인덱스

    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        # 광선이 현재 변(edge)과 교차하는지 확인
        # 조건 1: yi와 yj 사이에 y가 있어야 함
        # 조건 2: 교차점의 x가 현재 점의 x보다 오른쪽에 있어야 함
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside  # 교차할 때마다 내/외부 전환

        j = i  # 다음 반복에서 이전 꼭짓점

    return inside


# ════════════════════════════════════════════
# 2. 작업자 위치 기반 지오펜스 체크
# ════════════════════════════════════════════

def check_worker_in_geofences(worker_id: str, worker_name: str,
                               x: float, y: float) -> list:
    """
    작업자 좌표(x, y)가 어떤 지오펜스 안에 있는지 확인.
    진입이 감지된 지오펜스마다 알람을 생성하고 목록으로 반환.
    반환:
        [
          {
            "geofence_id": 1,
            "geofence_name": "위험구역 A",
            "zone_type": "danger",
            "alarm_id": 5,
            "alarm_level": "danger",
            "message": "작업자 A가 위험구역 A에 진입했습니다."
          },
          ...
        ]
    """
    results = []
    fences  = GeoFence.objects.filter(is_active=True)

    for fence in fences:
        if not fence.polygon or len(fence.polygon) < 3:
            continue

        if point_in_polygon(x, y, fence.polygon):
            # 알람 레벨 결정
            level = _zone_to_alarm_level(fence.zone_type)

            # 알람 메시지
            msg = f"{worker_name}이(가) [{fence.name}]에 진입했습니다. (zone: {fence.zone_type})"

            # DB 저장
            alarm = Alarm.objects.create(
                alarm_type  = 'geofence_enter',
                alarm_level = level,
                worker_id   = worker_id,
                worker_name = worker_name,
                worker_x    = x,
                worker_y    = y,
                geofence    = fence,
                message     = msg,
            )

            results.append({
                "geofence_id":   fence.id,
                "geofence_name": fence.name,
                "zone_type":     fence.zone_type,
                "alarm_id":      alarm.id,
                "alarm_level":   level,
                "message":       msg,
            })

    return results


# ════════════════════════════════════════════
# 3. 센서 상태 기반 알람 생성
# ════════════════════════════════════════════

def create_sensor_alarm(device_id: str, sensor_type: str,
                        status: str, detail: str = '') -> dict | None:
    """
    센서 상태가 caution 또는 danger일 때 알람 생성.
    normal이면 None 반환.
    """
    if status == 'normal':
        return None

    alarm_type  = 'sensor_caution' if status == 'caution' else 'sensor_danger'
    alarm_level = 'caution'        if status == 'caution' else 'danger'
    msg = f"센서 [{device_id}] {status.upper()} 상태 감지. {detail}"

    alarm = Alarm.objects.create(
        alarm_type  = alarm_type,
        alarm_level = alarm_level,
        device_id   = device_id,
        sensor_type = sensor_type,
        message     = msg,
    )

    return {
        "alarm_id":    alarm.id,
        "alarm_level": alarm_level,
        "alarm_type":  alarm_type,
        "message":     msg,
    }


# ════════════════════════════════════════════
# 4. 복합 알람 (진입 + 센서 동시)
# ════════════════════════════════════════════

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
        alarm_type  = 'combined',
        alarm_level = 'critical',
        worker_id   = worker_id,
        worker_name = worker_name,
        geofence    = geofence,
        device_id   = device_id,
        message     = msg,
    )

    return {
        "alarm_id":    alarm.id,
        "alarm_level": "critical",
        "alarm_type":  "combined",
        "message":     msg,
    }


# ════════════════════════════════════════════
# 5. 유틸
# ════════════════════════════════════════════

def _zone_to_alarm_level(zone_type: str) -> str:
    return {
        'danger':     'danger',
        'caution':    'caution',
        'restricted': 'critical',
    }.get(zone_type, 'caution')