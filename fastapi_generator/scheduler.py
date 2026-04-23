# scheduler.py — 개념 스케치

import asyncio
from datetime import datetime
import httpx

from generators import generate_gas, generate_power, move_worker
from django_loader import load_devices, load_workers
from poster import post_sensor_data, post_worker_location, post_check_geofence


async def run_simulation_loop(
    base_url: str,
    scenario: str = "mixed",
    interval_sec: float = 1.0,
) -> None:
    """
    FastAPI 시작 시 백그라운드 태스크로 기동.
    종료 신호 받을 때까지 무한 루프.
    """
    async with httpx.AsyncClient() as client:
        print("[scheduler] Django에서 초기 데이터 로드 중...")
        devices = await load_devices(client, base_url)
        workers = await load_workers(client, base_url)
        print(f"[scheduler] 장비 {len(devices)}개, 작업자 {len(workers)}명")
        
        tick = 0
        while True:
            await _tick(client, base_url, devices, workers, tick, scenario)
            tick += 1
            await asyncio.sleep(interval_sec)


async def _tick(client, base_url, devices, workers, tick, mode):
    """1초 주기 1회분 작업."""
    sensor_summary = []  # check-geofence 전송용
    
    # 1) 센서 5개 병렬 POST
    sensor_tasks = []
    for d in devices:
        if d["sensor_type"] == "gas":
            gas = generate_gas(tick, mode)
            sensor_tasks.append(post_sensor_data(client, base_url, d["device_id"], gas))
            # check-geofence 용 요약은 status 판정을 로컬에서 가볍게 (optional)
            # 더 깔끔하게는 Django의 응답에서 status 받아쓰기 (E 완료 후 최적화)
            sensor_summary.append({
                "device_id": d["device_id"],
                "sensor_type": "gas",
                "status": "normal",  # 임시. Django가 정확한 판정 → WS로 반영됨
                "detail": f"CO:{gas['co']}",
            })
        # power는 현재 Django SensorDataView가 받지 않음 (Phase F 정리 대상)
        # 여기선 일단 생성만 하고 미전송 (주석 표시)
    
    # 2) 작업자 위치 이동 + 병렬 POST
    worker_tasks = []
    worker_summary = []  # check-geofence 전송용
    for w in workers:
        move_worker(w)
        worker_tasks.append(
            post_worker_location(client, base_url, w["worker_db_pk"], w["x"], w["y"])
        )
        worker_summary.append({
            "worker_id": w["worker_id"],
            "name": w["name"],
            "x": round(w["x"]), "y": round(w["y"]),
        })
    
    # 3) 모든 저장 병렬 실행
    await asyncio.gather(*sensor_tasks, *worker_tasks)
    
    # 4) 알람 판정 트리거 (sensor_summary의 status는 임시이므로
    #    Django가 실제 최신 status로 검증 — 판정은 서버 권위)
    await post_check_geofence(client, base_url, worker_summary, sensor_summary)