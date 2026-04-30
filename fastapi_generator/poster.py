"""
poster.py — Django REST API 로 HTTP POST 전송

역할:
  - 생성된 데이터를 Django 에 전달 (저장 + WS push 트리거)
  - 실패 시 조용히 로그만 남기고 루프는 계속 진행 (resilience)

3가지 엔드포인트:
  1. POST /dashboard/api/sensor-data/    — 센서 1개의 현재값 (gas 또는 power)
  2. POST /dashboard/api/worker-location/ — 작업자 1명의 현재 좌표
  3. POST /dashboard/api/check-geofence/  — 알람 판정 트리거 (일괄)

설계 원칙:
  - 인증은 config.INTERNAL_HEADERS 의 X-Internal-API-Key 로
  - 실패는 RuntimeError 로 올리지 않음 (1틱 실패가 전체 루프를 끊으면 안 됨)
  - 성공/실패 명시적 반환 — scheduler 가 응답 status 를 재활용

[E5 변경점]
  post_sensor_data:
    - 시그니처 변경: (client, device_id, gas) → (client, device_id, sensor_type, values)
    - power 도 수용 (sensor_type="power", values={"current":..., "voltage":..., "watt":...})
    - 반환 타입 추가: dict | None (성공 시 Django 응답 JSON, 실패 시 None)
      응답 형태: {"id": <sd_id>, "status": "normal"|"caution"|"danger"}
"""

import httpx

from config import DJANGO_BASE_URL, INTERNAL_HEADERS


async def post_sensor_data(
    client: httpx.AsyncClient,
    device_id: str,
    sensor_type: str,
    values: dict,
) -> dict | None:
    """
    센서 값 1건 저장.

    Django 가 수신 → SensorData 저장 → status 판정 → publish_sensor_update.

    Args:
        client: 재사용되는 AsyncClient
        device_id: 'sensor_01' / 'power_02' 등
        sensor_type: 'gas' | 'power'
        values: sensor_type 별 측정값 dict
            gas  → {"co":..., "h2s":..., "co2":..., "o2":..., "no2":...,
                    "so2":..., "o3":..., "nh3":..., "voc":...}
            power→ {"current":..., "voltage":..., "watt":...}

    Returns:
        성공: {"id": int, "status": "normal"|"caution"|"danger"}
        실패: None (네트워크 예외 / HTTP 4xx·5xx)

        scheduler 는 이 status 를 받아 check-geofence 의 sensors[].status 에 재활용.
    """
    url = f"{DJANGO_BASE_URL}/dashboard/api/sensor-data/"
    payload = {"device_id": device_id, "sensor_type": sensor_type, **values}

    try:
        res = await client.post(
            url, json=payload, headers=INTERNAL_HEADERS, timeout=3.0
        )
        if res.status_code >= 400:
            print(
                f"[poster] sensor-data {device_id} {res.status_code}: {res.text[:200]}"
            )
            return None
        return res.json()
    except httpx.HTTPError as e:
        print(f"[poster] sensor-data {device_id} 예외: {type(e).__name__}")
        return None


async def post_worker_location(
    client: httpx.AsyncClient,
    worker_db_pk: int,
    x: float,
    y: float,
) -> None:
    """
    작업자 위치 저장.
    Django 가 수신 → WorkerLocation 저장 → publish_worker_position.
    """
    url = f"{DJANGO_BASE_URL}/dashboard/api/worker-location/"
    payload = {
        "worker": worker_db_pk,
        "x": round(x, 1),
        "y": round(y, 1),
        "movement_status": "moving",
    }

    try:
        res = await client.post(
            url, json=payload, headers=INTERNAL_HEADERS, timeout=3.0
        )
        if res.status_code >= 400:
            print(
                f"[poster] worker-location pk={worker_db_pk} {res.status_code}: {res.text[:200]}"
            )
    except httpx.HTTPError as e:
        print(f"[poster] worker-location pk={worker_db_pk} 예외: {type(e).__name__}")


async def post_check_geofence(
    client: httpx.AsyncClient,
    workers: list[dict],
    sensors: list[dict],
) -> None:
    """
    지오펜스 + 근접 센서 기반 상태 전이 알람 판정 트리거.
    Django 의 CheckGeofenceView 가 evaluate_worker / evaluate_sensor 호출 →
    상태 전이 기반 알람 생성 → publish_alarm.

    Args:
        workers: [{"worker_id", "name", "x", "y"}, ...]
        sensors: [{"device_id", "sensor_type", "status", "detail", "x", "y"}, ...]
                 x, y 는 CheckGeofenceView 의 PROXIMITY_RADIUS(=200px) 판정용.
                 status 는 Django SensorDataView 가 직전에 판정해 돌려준 값.
    """
    url = f"{DJANGO_BASE_URL}/dashboard/api/check-geofence/"
    payload = {"workers": workers, "sensors": sensors}

    try:
        res = await client.post(
            url, json=payload, headers=INTERNAL_HEADERS, timeout=3.0
        )
        if res.status_code >= 400:
            print(f"[poster] check-geofence {res.status_code}: {res.text[:200]}")
    except httpx.HTTPError as e:
        print(f"[poster] check-geofence 예외: {type(e).__name__}")
