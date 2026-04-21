import asyncio
import json
import math
import random
import httpx
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DJANGO_BASE_URL = "http://127.0.0.1:8000"

# ════════════════════════════════════════
# 폴백용 하드코딩 데이터 (Django API 실패 시)
# ════════════════════════════════════════
SENSOR_DEVICES_FALLBACK = [
    {"device_id": "sensor_01", "device_name": "가스센서 A", "sensor_type": "gas",   "x": 200, "y": 150},
    {"device_id": "sensor_02", "device_name": "가스센서 B", "sensor_type": "gas",   "x": 500, "y": 180},
    {"device_id": "sensor_03", "device_name": "가스센서 C", "sensor_type": "gas",   "x": 350, "y": 390},
    {"device_id": "power_01",  "device_name": "스마트파워 A", "sensor_type": "power", "x": 620, "y": 100},
    {"device_id": "power_02",  "device_name": "스마트파워 B", "sensor_type": "power", "x": 130, "y": 390},
]

WORKERS_FALLBACK = [
    {"worker_id": "worker_01", "name": "작업자 A", "x": 300.0, "y": 250.0, "dx": 2.5,  "dy": 1.5},
    {"worker_id": "worker_02", "name": "작업자 B", "x": 500.0, "y": 400.0, "dx": -2.0, "dy": 2.0},
]

# ════════════════════════════════════════
# Django API에서 데이터 로드
# ════════════════════════════════════════
async def load_devices_from_django() -> list:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{DJANGO_BASE_URL}/dashboard/api/device/")
            if res.status_code == 200:
                data = res.json()
                items = data.get("results", data) if isinstance(data, dict) else data
                devices = [
                    {
                        "device_id":   item["device_id"],
                        "device_name": item["device_name"],
                        "sensor_type": item["sensor_type"],
                        "x": float(item.get("x", 0)),
                        "y": float(item.get("y", 0)),
                    }
                    for item in items
                ]
                print(f"[FastAPI] 장비 {len(devices)}개 Django DB에서 로드")
                return devices
    except Exception as e:
        print(f"[FastAPI] 장비 로드 실패 → 폴백 사용: {e}")
    return SENSOR_DEVICES_FALLBACK


async def load_geofences_from_django() -> list:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{DJANGO_BASE_URL}/dashboard/api/geofence/")
            if res.status_code == 200:
                data = res.json()
                items = data.get("results", data) if isinstance(data, dict) else data
                fences = [
                    {
                        "name":      item["name"],
                        "zone_type": item.get("zone_type", "danger"),
                        "polygon":   item["polygon"],
                    }
                    for item in items
                ]
                print(f"[FastAPI] 지오펜스 {len(fences)}개 Django DB에서 로드")
                return fences
    except Exception as e:
        print(f"[FastAPI] 지오펜스 로드 실패: {e}")
    return []


async def load_workers_from_django() -> list:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{DJANGO_BASE_URL}/dashboard/api/worker/")
            if res.status_code == 200:
                data = res.json()
                items = data.get("results", data) if isinstance(data, dict) else data
                workers = [
                    {
                        "worker_id": item["worker_id"],
                        "name":      item["name"],
                        "x":         200.0 + i * 150 + random.random() * 50,
                        "y":         200.0 + i * 100 + random.random() * 50,
                        "dx":        (random.random() - 0.5) * 4,
                        "dy":        (random.random() - 0.5) * 4,
                    }
                    for i, item in enumerate(items)
                ]
                print(f"[FastAPI] 작업자 {len(workers)}명 Django DB에서 로드")
                return workers
    except Exception as e:
        print(f"[FastAPI] 작업자 로드 실패 → 폴백 사용: {e}")
    return WORKERS_FALLBACK


# ════════════════════════════════════════
# 센서 데이터 Django DB에 저장
# ════════════════════════════════════════
async def save_sensor_data_to_django(device_id: str, gas: dict):
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            payload = {"device_id": device_id, **gas}
            await client.post(
                f"{DJANGO_BASE_URL}/dashboard/api/sensor-data/",
                json=payload,
            )
    except Exception:
        pass


# ════════════════════════════════════════
# 가스 임계치
# ════════════════════════════════════════
GAS_THRESHOLDS = {
    "co":  {"normal": 25,   "danger": 200},
    "h2s": {"normal": 10,   "danger": 50},
    "co2": {"normal": 1000, "danger": 5000},
    "o2":  {"low": 18.0,    "high": 23.5},
    "no2": {"normal": 3,    "danger": 5},
    "so2": {"normal": 2,    "danger": 5},
    "o3":  {"normal": 0.05, "danger": 0.1},
    "nh3": {"normal": 25,   "danger": 50},
    "voc": {"normal": 0.5,  "danger": 2.0},
}

GAS_NORMAL_CENTER = {
    "co": 12, "h2s": 2, "co2": 600, "o2": 20.9,
    "no2": 0.04, "so2": 0.2, "o3": 0.02, "nh3": 8, "voc": 0.15,
}

MARGIN = 40
IMG_W  = 1360
IMG_H  = 960

alarm_cache: dict = {}
ALARM_COOLDOWN = 30


# ════════════════════════════════════════
# 데이터 생성 함수
# ════════════════════════════════════════
def gauss(center, std, min_val, max_val):
    z = math.sqrt(-2 * math.log(max(1e-10, random.random()))) * math.cos(2 * math.pi * random.random())
    return min(max_val, max(min_val, center + z * std))


def generate_gas(tick: int, mode: str = "mixed") -> dict:
    g = {
        "co":  gauss(GAS_NORMAL_CENTER["co"],  3,     0,   500),
        "h2s": gauss(GAS_NORMAL_CENTER["h2s"], 1,     0,   100),
        "co2": gauss(GAS_NORMAL_CENTER["co2"], 80,    300, 10000),
        "o2":  gauss(GAS_NORMAL_CENTER["o2"],  0.2,   15,  25),
        "no2": gauss(GAS_NORMAL_CENTER["no2"], 0.01,  0,   5),
        "so2": gauss(GAS_NORMAL_CENTER["so2"], 0.05,  0,   10),
        "o3":  gauss(GAS_NORMAL_CENTER["o3"],  0.005, 0,   0.5),
        "nh3": gauss(GAS_NORMAL_CENTER["nh3"], 2,     0,   100),
        "voc": gauss(GAS_NORMAL_CENTER["voc"], 0.03,  0,   5),
    }
    if mode == "mixed":
        if tick % 30 == 0 and tick > 0: g["co"]  = 30 + random.random() * 50
        if tick % 60 == 0 and tick > 0: g["h2s"] = 12 + random.random() * 15
        if tick % 45 == 0 and tick > 0: g["o2"]  = 16 + random.random() * 2
        if random.random() < 0.05:      g["voc"] = 0.6 + random.random() * 1.0
    elif mode == "danger":
        g["co"]  = 200  + random.random() * 150
        g["h2s"] = 50   + random.random() * 30
        g["co2"] = 5000 + random.random() * 3000
        g["o2"]  = 12   + random.random() * 4
    return {k: round(v, 2) for k, v in g.items()}


def generate_power(tick: int, mode: str = "mixed") -> dict:
    current = gauss(12, 2, 0, 50)
    voltage = gauss(220, 3, 190, 250)
    if mode == "danger":
        current = 30 + random.random() * 15
        voltage = 195 + random.random() * 10
    elif mode == "mixed" and tick % 50 == 0 and tick > 0:
        current = 22 + random.random() * 8
    return {
        "current": round(current, 2),
        "voltage": round(voltage, 2),
        "watt":    round(current * voltage, 1),
    }


def classify_gas_status(gas: dict) -> str:
    o2 = gas.get("o2")
    if o2 is not None:
        if o2 < 16 or o2 >= 23.5: return "danger"
        if o2 < 18 or o2 > 21.5:
            worst = "caution"
        else:
            worst = "normal"
    else:
        worst = "normal"

    for key, value in gas.items():
        t = GAS_THRESHOLDS.get(key)
        if not t or "danger" not in t: continue
        if value >= t["danger"]: return "danger"
        if value >= t.get("normal", 0) and worst == "normal":
            worst = "caution"
    return worst


def classify_power_status(power: dict) -> str:
    if power["current"] >= 30 or power["watt"] >= 8000: return "danger"
    if power["current"] >= 20 or power["voltage"] < 200 or power["voltage"] > 240: return "caution"
    return "normal"


def move_worker(worker: dict):
    worker["dx"] += (random.random() - 0.5) * 0.6
    worker["dy"] += (random.random() - 0.5) * 0.6
    worker["dx"] = max(-4, min(4, worker["dx"]))
    worker["dy"] = max(-4, min(4, worker["dy"]))
    worker["x"] += worker["dx"]
    worker["y"] += worker["dy"]
    if worker["x"] < MARGIN or worker["x"] > IMG_W - MARGIN:
        worker["dx"] = -worker["dx"]
        worker["x"] = max(MARGIN, min(IMG_W - MARGIN, worker["x"]))
    if worker["y"] < MARGIN or worker["y"] > IMG_H - MARGIN:
        worker["dy"] = -worker["dy"]
        worker["y"] = max(MARGIN, min(IMG_H - MARGIN, worker["y"]))


# ════════════════════════════════════════
# 지오펜스 판단
# ════════════════════════════════════════
def point_in_polygon(x: float, y: float, polygon: list) -> bool:
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-10) + xi):
            inside = not inside
        j = i
    return inside


def check_geofence_alarm(worker: dict, geofences: list, sensor_data: list) -> dict | None:
    for fence in geofences:
        polygon = fence.get("polygon", [])
        if not polygon: continue
        if point_in_polygon(worker["x"], worker["y"], polygon):
            for sensor in sensor_data:
                if sensor.get("sensor_type") == "gas" and sensor.get("status") == "danger":
                    alarm_key = f"{worker['worker_id']}-{fence['name']}-{sensor['device_id']}"
                    now  = asyncio.get_event_loop().time()
                    last = alarm_cache.get(alarm_key, 0)
                    if now - last < ALARM_COOLDOWN: continue
                    alarm_cache[alarm_key] = now
                    return {
                        "type":          "alert",
                        "timestamp":     datetime.now().isoformat(),
                        "level":         "danger",
                        "worker_id":     worker["worker_id"],
                        "worker_name":   worker["name"],
                        "geofence_name": fence["name"],
                        "sensor_id":     sensor["device_id"],
                        "message":       f"{worker['name']}이 {fence['name']} 내부에서 위험 수치 감지",
                    }
    return None


# ════════════════════════════════════════
# WebSocket 엔드포인트
# ════════════════════════════════════════
@app.websocket("/ws/sensors/")
async def websocket_sensors(websocket: WebSocket):
    await websocket.accept()
    tick = 0
    mode = "mixed"

    # Django DB에서 데이터 로드
    devices   = await load_devices_from_django()
    geofences = await load_geofences_from_django()
    workers   = await load_workers_from_django()

    print(f"[FastAPI] 장비:{len(devices)}개 / 지오펜스:{len(geofences)}개 / 작업자:{len(workers)}명")

    try:
        while True:
            sensor_data_list = []

            for device in devices:
                if device["sensor_type"] == "gas":
                    gas    = generate_gas(tick, mode)
                    status = classify_gas_status(gas)
                    sensor_data_list.append({
                        "device_id":   device["device_id"],
                        "device_name": device["device_name"],
                        "sensor_type": "gas",
                        "x": device["x"], "y": device["y"],
                        "gas":    gas,
                        "status": status,
                    })
                    # 10틱마다 DB 저장
                    if tick % 10 == 0:
                        await save_sensor_data_to_django(device["device_id"], gas)
                else:
                    power  = generate_power(tick, mode)
                    status = classify_power_status(power)
                    sensor_data_list.append({
                        "device_id":   device["device_id"],
                        "device_name": device["device_name"],
                        "sensor_type": "power",
                        "x": device["x"], "y": device["y"],
                        "power":  power,
                        "status": status,
                    })

            # 작업자 이동
            worker_data_list = []
            for worker in workers:
                move_worker(worker)
                worker_data_list.append({
                    "worker_id": worker["worker_id"],
                    "name":      worker["name"],
                    "x":         round(worker["x"], 1),
                    "y":         round(worker["y"], 1),
                })

            # 통합 메시지 전송
            await websocket.send_text(json.dumps({
                "type":      "update",
                "timestamp": datetime.now().isoformat(),
                "tick":      tick,
                "sensors":   sensor_data_list,
                "workers":   worker_data_list,
            }, ensure_ascii=False))

            # 지오펜스 판단 → 알람 전송
            for worker in workers:
                alarm = check_geofence_alarm(worker, geofences, sensor_data_list)
                if alarm:
                    await websocket.send_text(json.dumps(alarm, ensure_ascii=False))

            tick += 1
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        print(f"[FastAPI] 클라이언트 연결 종료 (tick={tick})")


# ════════════════════════════════════════
# 헬스체크
# ════════════════════════════════════════
@app.get("/health")
def health():
    return {"status": "ok", "django": DJANGO_BASE_URL}
