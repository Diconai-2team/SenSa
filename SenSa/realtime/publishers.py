"""
realtime/publishers.py — Channel Layer로 메시지 발행하는 얇은 래퍼

왜 분리하나:
  3차: 동기적으로 channel_layer에 바로 push
  4차: 같은 함수 시그니처를 유지한 채 내부만 Celery로 교체 예정
       → views.py, services.py의 호출부는 한 줄도 안 바뀜

규칙:
  - 이 파일은 '어디로 보낼지'만 담당. '왜 보내는지'는 호출자가 결정.
  - 외부 함수 4종만 노출 (publish_*).
  - 내부 _send()가 실제 Channel Layer 호출을 감춤.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _send(group: str, event_type: str, payload: dict) -> None:
    """
    Channel Layer group_send의 공통 래퍼.
    
    event_type에 점(.)이 있으면 Consumer의 메서드명에서 점이 밑줄로 변환됨.
    예: "alarm.new" → Consumer.alarm_new()
    
    payload는 Consumer 핸들러에서 그대로 접근 가능한 딕셔너리.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        # CHANNEL_LAYERS 설정이 비어있을 때를 대비한 방어 코드
        # 실제로는 settings.py에 설정돼 있으니 여기까지 오면 설정 문제
        return
    
    async_to_sync(channel_layer.group_send)(
        group,
        {
            "type": event_type,
            "payload": payload,
        },
    )


# ═══════════════════════════════════════════════════════════
# 외부 노출 함수 — views.py, services.py에서 import해서 씀
# ═══════════════════════════════════════════════════════════

def publish_alarm(alarm_dict: dict) -> None:
    """
    알람 하나를 dashboard.alarms 그룹에 방송.
    
    alarm_dict 예시:
      {
        "alarm_id": 123,
        "alarm_type": "geofence_enter",
        "alarm_level": "danger",
        "message": "작업자 A가 고온구역 A에 진입",
        "worker_id": "worker_01",
        "worker_name": "작업자 A",
        "geofence_id": 5,
        "geofence_name": "고온구역 A",
      }
    
    호출하는 쪽:
      - CheckGeofenceView에서 알람 생성 직후
      - Phase D 이후에는 다른 알람 생성 지점에서도
    """
    _send("dashboard.alarms", "alarm.new", alarm_dict)

# ═══════════════════════════════════════════════════════════
# 외부 노출 함수 — views.py, services.py에서 import해서 씀
# ═══════════════════════════════════════════════════════════

def publish_worker_position(worker_data: dict) -> None:
    """
    작업자 1명의 최신 위치를 dashboard.workers 그룹에 방송.
    
    worker_data 예시:
      {
        "worker_id": "worker_01",
        "worker_name": "김재승",
        "x": 234.5,
        "y": 180.2,
        "movement_status": "moving",
        "timestamp": "2026-04-21T11:30:45+09:00",
      }
    
    호출 지점:
      workers/views.py의 WorkerLocationViewSet.perform_create()
    """
    _send("dashboard.workers", "worker.position", worker_data)


def publish_sensor_update(sensor_data: dict) -> None:
    """
    센서 1개의 최신 측정값을 dashboard.sensors 그룹에 방송.
    
    sensor_data 예시:
      {
        "device_id": "sensor_01",
        "sensor_type": "gas",
        "status": "caution",
        "values": {"co": 35.2, "h2s": 4.1, "co2": 850, "o2": 20.8, ...},
        "timestamp": "2026-04-21T11:30:45+09:00",
      }
    
    호출 지점:
      devices/views.py의 SensorDataView.post()
    """
    _send("dashboard.sensors", "sensor.update", sensor_data)