"""
poster.py — Django REST API 로 HTTP POST 전송

역할:
  - 생성된 데이터를 Django 에 전달 (저장 + WS push 트리거)
  - 실패 시 조용히 로그만 남기고 루프는 계속 진행 (resilience)

3가지 엔드포인트:
  1. POST /dashboard/api/sensor-data/   — 센서 1개의 현재값
  2. POST /dashboard/api/worker-location/ — 작업자 1명의 현재 좌표
  3. POST /dashboard/api/check-geofence/  — 알람 판정 트리거 (일괄)

주의:
  - 인증은 config.INTERNAL_HEADERS 의 X-Internal-API-Key 로
  - 실패는 RuntimeError 로 올리지 않음 (1틱 실패가 전체 루프를 끊으면 안 됨)
"""
import httpx

from config import DJANGO_BASE_URL, INTERNAL_HEADERS


async def post_sensor_data(
    client: httpx.AsyncClient,
    device_id: str,
    gas: dict,
) -> None:
    """
    센서 값 1건 저장.
    Django가 수신 → SensorData 저장 → status 판정 → publish_sensor_update.
    """
    url = f"{DJANGO_BASE_URL}/dashboard/api/sensor-data/"
    payload = {"device_id": device_id, **gas}

    try:
        res = await client.post(url, json=payload, headers=INTERNAL_HEADERS, timeout=3.0)
        if res.status_code >= 400:
            print(f"[poster] sensor-data {device_id} {res.status_code}: {res.text[:200]}")
    except httpx.HTTPError as e:
        print(f"[poster] sensor-data {device_id} 예외: {type(e).__name__}")


async def post_worker_location(
    client: httpx.AsyncClient,
    worker_db_pk: int,
    x: float,
    y: float,
) -> None:
    """
    작업자 위치 저장.
    Django가 수신 → WorkerLocation 저장 → publish_worker_position.
    """
    url = f"{DJANGO_BASE_URL}/dashboard/api/worker-location/"
    payload = {
        "worker": worker_db_pk,
        "x": round(x, 1),
        "y": round(y, 1),
        "movement_status": "moving",
    }

    try:
        res = await client.post(url, json=payload, headers=INTERNAL_HEADERS, timeout=3.0)
        if res.status_code >= 400:
            print(f"[poster] worker-location pk={worker_db_pk} {res.status_code}: {res.text[:200]}")
    except httpx.HTTPError as e:
        print(f"[poster] worker-location pk={worker_db_pk} 예외: {type(e).__name__}")


async def post_check_geofence(
    client: httpx.AsyncClient,
    workers: list[dict],
    sensors: list[dict],
) -> None:
    """
    지오펜스 + 복합 위험 판정 트리거.
    Django의 CheckGeofenceView가 판정 + 알람 생성 + publish_alarm.

    workers 각 요소: {"worker_id", "name", "x", "y"}
    sensors 각 요소: {"device_id", "sensor_type", "status", "detail"}
                    (status != "normal" 인 것만 전달)
    """
    url = f"{DJANGO_BASE_URL}/dashboard/api/check-geofence/"
    payload = {"workers": workers, "sensors": sensors}

    try:
        res = await client.post(url, json=payload, headers=INTERNAL_HEADERS, timeout=3.0)
        if res.status_code >= 400:
            print(f"[poster] check-geofence {res.status_code}: {res.text[:200]}")
    except httpx.HTTPError as e:
        print(f"[poster] check-geofence 예외: {type(e).__name__}")