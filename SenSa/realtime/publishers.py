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

# 비동기 함수를 동기 컨텍스트(일반 Django view, 시그널 등)에서 호출할 수 있게 변환해 주는 유틸리티.
# Channel Layer의 group_send는 async 함수이므로, 동기 코드에서 쓰려면 이 래퍼가 필요함.

from channels.layers import get_channel_layer

# 현재 설정(settings.py의 CHANNEL_LAYERS)에 연결된 Channel Layer 인스턴스를 가져오는 함수.
# Channel Layer는 Redis 같은 외부 브로커를 통해 서버 내 서로 다른 프로세스가 메시지를 주고받는 버스 역할.


def _send(group: str, event_type: str, payload: dict) -> None:
    """
    Channel Layer group_send의 공통 래퍼.

    event_type에 점(.)이 있으면 Consumer의 메서드명에서 점이 밑줄로 변환됨.
    예: "alarm.new" → Consumer.alarm_new()

    payload는 Consumer 핸들러에서 그대로 접근 가능한 딕셔너리.
    """
    # 이 파일의 모든 publish_* 함수가 내부적으로 호출하는 공통 발송 함수.
    # 중복 코드 없이 Channel Layer 연동 로직을 한 곳에 모아둠.

    channel_layer = get_channel_layer()
    # 현재 연결된 Channel Layer 인스턴스(Redis 등)를 가져옴.

    if channel_layer is None:
        # CHANNEL_LAYERS 설정이 비어있을 때를 대비한 방어 코드
        # 실제로는 settings.py에 설정돼 있으니 여기까지 오면 설정 문제
        return
        # Channel Layer가 설정되지 않은 환경(테스트, 로컬 개발 등)에서 조용히 무시.
        # 예외를 던지지 않으므로 WS 미설정 환경에서도 서버가 죽지 않음.

    async_to_sync(channel_layer.group_send)(
        # 비동기 group_send를 동기 함수처럼 즉시 실행.
        group,
        # 메시지를 전달할 Channel Layer 그룹 이름 (예: "dashboard.alarms").
        {
            "type": event_type,
            # Consumer에서 어떤 메서드를 호출할지 결정하는 키.
            # "alarm.new"이면 consumers.py의 alarm_new() 메서드로 라우팅됨.
            "payload": payload,
            # 실제 전달할 데이터. Consumer 핸들러에서 event["payload"]로 접근.
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
    # "dashboard.alarms" 그룹을 구독 중인 모든 브라우저에게 새 알람 데이터를 즉시 푸시.
    # Consumer의 alarm_new() 핸들러가 받아서 브라우저로 최종 전달함.


# ═══════════════════════════════════════════════════════════
# 외부 노출 함수 — views.py, services.py에서 import해서 씀
# ═══════════════════════════════════════════════════════════


def publish_alarm(alarm_dict: dict) -> None:
    """(기존 코드 그대로)"""
    _send("dashboard.alarms", "alarm.new", alarm_dict)
    # 위의 publish_alarm과 동일한 함수가 중복 선언되어 있음.
    # Python에서 같은 이름의 함수를 두 번 정의하면 아래 것이 위를 덮어쓰므로, 실제로는 이 버전만 사용됨.
    # 정리가 필요한 코드: 둘 중 하나를 제거해야 함.


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
    # 작업자의 좌표·상태 데이터를 "dashboard.workers" 그룹 전체에 브로드캐스트.
    # Consumer의 worker_position() 핸들러가 받아서 프론트엔드 지도 마커를 실시간으로 이동시킴.


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
    # 새 센서 측정값을 "dashboard.sensors" 그룹 전체에 브로드캐스트.
    # Consumer의 sensor_update() 핸들러가 받아서 대시보드의 센서 카드·수치를 실시간으로 갱신함.
