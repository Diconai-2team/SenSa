"""
django_loader.py — FastAPI 기동 시 Django DB에서 초기 상태를 로드한다.

역할:
  - 활성 센서 목록 로드
  - 작업자 목록 + 각자의 마지막 위치 로드
  - (선택) 지오펜스 목록 — FastAPI는 판정하지 않지만 디버그 출력용

설계 원칙:
  - Django 연결 실패 시 폴백 데이터 사용하지 않음 (fail fast)
  - FastAPI 기동 단계에서만 호출 — 이후 매 틱마다 다시 로드하지는 않음
    (4차에서 Redis pub/sub 으로 동적 갱신 예정)
"""

import httpx

from config import DJANGO_BASE_URL, INTERNAL_HEADERS


async def load_devices(client: httpx.AsyncClient) -> list[dict]:
    """활성 센서 목록."""
    res = await client.get(
        f"{DJANGO_BASE_URL}/dashboard/api/device/",
        headers=INTERNAL_HEADERS,
    )
    res.raise_for_status()
    data = res.json()
    items = data.get("results", data) if isinstance(data, dict) else data

    return [
        {
            "device_id": it["device_id"],
            "device_name": it["device_name"],
            "sensor_type": it["sensor_type"],
            "x": float(it.get("x", 0)),
            "y": float(it.get("y", 0)),
        }
        for it in items
    ]


async def load_workers(client: httpx.AsyncClient) -> list[dict]:
    """
    작업자 목록 + 각자의 마지막 위치.

    Phase D3 에서 WorkerLocation 이 매초 저장되므로,
    FastAPI 재기동 시에도 마지막 좌표부터 이어서 시뮬레이션할 수 있다.
    """
    res = await client.get(
        f"{DJANGO_BASE_URL}/dashboard/api/worker/",
        headers=INTERNAL_HEADERS,
    )
    res.raise_for_status()
    data = res.json()
    items = data.get("results", data) if isinstance(data, dict) else data

    workers = []
    for item in items:
        x, y = await _fetch_last_location(client, item["id"])
        workers.append(
            {
                "worker_db_pk": item["id"],
                "worker_id": item["worker_id"],
                "name": item["name"],
                "x": x,
                "y": y,
                "dx": 0.0,
                "dy": 0.0,
            }
        )
    return workers


async def _fetch_last_location(
    client: httpx.AsyncClient, worker_db_pk: int
) -> tuple[float, float]:
    """WorkerLocation 최신 1건. 없으면 기본 초기 좌표."""
    res = await client.get(
        f"{DJANGO_BASE_URL}/dashboard/api/worker/{worker_db_pk}/latest/",
        headers=INTERNAL_HEADERS,
    )
    if res.status_code == 200:
        d = res.json()
        return float(d.get("x", 200)), float(d.get("y", 200))
    return 200.0, 200.0


async def load_geofences(client: httpx.AsyncClient) -> list[dict]:
    """
    지오펜스 목록.

    주의: FastAPI는 지오펜스 판정을 직접 하지 않는다.
    (판정은 Django alerts/services.py 의 단일 책임)
    여기서는 로딩만 하고 디버그 로그로만 사용.
    """
    res = await client.get(
        f"{DJANGO_BASE_URL}/dashboard/api/geofence/",
        headers=INTERNAL_HEADERS,
    )
    res.raise_for_status()
    data = res.json()
    items = data.get("results", data) if isinstance(data, dict) else data
    return [{"name": it["name"], "polygon": it["polygon"]} for it in items]


async def load_thresholds(client: httpx.AsyncClient) -> dict:
    """
    Django 백오피스에서 임계치 데이터를 로드.

    응답 형식 (Django backoffice/views.py: thresholds_for_fastapi):
      {
        "categories": { "TH_GAS": {...}, ... },
        "flat":       { "TH_GAS.co": {item_code, operator, caution, danger, ...}, ... }
      }

    이 함수는 응답 JSON 을 그대로 반환하고,
    generators.apply_thresholds() 가 받아 GAS_THRESHOLDS 갱신.

    Returns:
        백오피스 응답 dict 또는 None (실패 시).

    Note:
        이 호출은 fail-soft. 실패해도 기본 (하드코딩) 임계치로 동작 유지.
    """
    try:
        res = await client.get(
            f"{DJANGO_BASE_URL}/dashboard/api/thresholds/",
            headers=INTERNAL_HEADERS,
            timeout=3.0,
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[django_loader] load_thresholds 실패 (fallback 유지): {e!r}")
        return None
