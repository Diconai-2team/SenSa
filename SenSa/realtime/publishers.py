"""
realtime/publishers.py — Channel Layer로 메시지 발행하는 얇은 래퍼

[Phase I-2 변경]
  - 중복 정의된 publish_alarm 정리 (단일 정의)
  - publish_zone_event 추가 — 동적 zone 라이프사이클 이벤트 발행

왜 분리하나:
  - 호출자(views.py, services.py, events.py)가 채널 레이어 API 를 직접
    안 만지게 함. 추후 내부를 Celery 로 교체해도 호출부 무수정.

규칙:
  - '어디로 보낼지'만 담당. '왜 보내는지'는 호출자가 결정.
  - 외부 함수만 노출 (publish_*).
  - 내부 _send()가 실제 Channel Layer 호출을 감춤.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _send(group: str, event_type: str, payload: dict) -> None:
    """
    Channel Layer group_send 의 공통 래퍼.

    event_type 의 점(.)은 Consumer 의 메서드명에서 밑줄로 변환됨.
    예: "alarm.new"  → Consumer.alarm_new()
        "zone.event" → Consumer.zone_event()
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        group,
        {
            "type": event_type,
            "payload": payload,
        },
    )


# ═══════════════════════════════════════════════════════════
# 외부 노출 함수
# ═══════════════════════════════════════════════════════════

def publish_alarm(alarm_dict: dict) -> None:
    """
    알람 하나를 dashboard.alarms 그룹에 방송.

    alarm_dict 예시:
      {
        "alarm_id": 123,
        "alarm_type": "geofence_enter",
        "alarm_level": "danger",
        "message": "[긴급][실측] worker_A 위험구역 진입",
        "worker_id": "worker_01",
        ...
      }

    호출 지점:
      - dashboard 의 CheckGeofenceView 등 알람 생성 직후
    """
    _send("dashboard.alarms", "alarm.new", alarm_dict)


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
        "values": {"co": 35.2, "h2s": 4.1, ...},
        "timestamp": "2026-04-21T11:30:45+09:00",
      }
    """
    _send("dashboard.sensors", "sensor.update", sensor_data)


def publish_zone_event(event_dict: dict) -> None:
    """
    [Phase I-2] 동적 zone 라이프사이클 이벤트를 dashboard.zones 그룹에 방송.

    event_dict 예시:
      {
        "event_id": 42,
        "event_type": "upgraded_to_critical",
        "zone_id": 53,
        "zone_name": "[자동] sensor_01 CO 확산",
        "from_tier": "confirmed",
        "to_tier": "critical",
        "trigger_source": "ttm_anomaly",
        "detail": {"confirmed_devices_count": 3, "radius_px": 200.0},
        "created_at": "2026-05-13T14:30:00",
      }

    호출 지점:
      geofence.events._emit() — ZoneEvent 생성 직후 자동 호출
    """
    _send("dashboard.zones", "zone.event", event_dict)
