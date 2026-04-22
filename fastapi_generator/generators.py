"""
generators.py — 센서값 / 작업자 위치 시뮬레이션 데이터 생성

팀원 FastAPI 초안의 데이터 생성부를 그대로 가져와 정제.
상태(status) 판정은 Django SensorDataView 가 수행하므로 여기선 뺌.
"""
import math
import random


# ═══════════════════════════════════════════════════════════
# 가스 임계치 (KOSHA, ACGIH, NIOSH 기준)
# Django 쪽 판정과 반드시 일치해야 함 — Phase F 통합 예정
# ═══════════════════════════════════════════════════════════
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

# 작업자 이동 한계 (이미지 좌표계)
MARGIN = 40
IMG_W  = 1360
IMG_H  = 960


def gauss(center: float, std: float, min_val: float, max_val: float) -> float:
    """박스-뮬러 변환 기반 정규분포 샘플, min/max 클램핑."""
    z = math.sqrt(-2 * math.log(max(1e-10, random.random()))) \
        * math.cos(2 * math.pi * random.random())
    return min(max_val, max(min_val, center + z * std))


def generate_gas(tick: int, mode: str = "mixed") -> dict:
    """
    9종 가스 측정값 1틱 분 생성.
    mode: "normal" | "mixed" | "danger"
    """
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
        # 주기적 이상 상황 섞기 (주의 레벨)
        if tick % 30 == 0 and tick > 0:
            g["co"] = 30 + random.random() * 50
        if tick % 60 == 0 and tick > 0:
            g["h2s"] = 12 + random.random() * 15
        if tick % 45 == 0 and tick > 0:
            g["o2"] = 16 + random.random() * 2
        if random.random() < 0.05:
            g["voc"] = 0.6 + random.random() * 1.0
        if tick % 90 == 0 and tick > 0:
            g["nh3"] = 30 + random.random() * 25

    elif mode == "danger":
        # 전역 위험 수치
        g["co"]  = 200  + random.random() * 150
        g["h2s"] = 50   + random.random() * 30
        g["co2"] = 5000 + random.random() * 3000
        g["o2"]  = 12   + random.random() * 4
        g["no2"] = 1.0  + random.random() * 2
        g["voc"] = 2.0  + random.random() * 2

    # 소수점 정리
    return {
        "co":  round(g["co"],  2),
        "h2s": round(g["h2s"], 2),
        "co2": round(g["co2"], 1),
        "o2":  round(g["o2"],  1),
        "no2": round(g["no2"], 3),
        "so2": round(g["so2"], 2),
        "o3":  round(g["o3"],  3),
        "nh3": round(g["nh3"], 1),
        "voc": round(g["voc"], 2),
    }


def generate_power(tick: int, mode: str = "mixed") -> dict:
    """
    전력 데이터 1틱 분 생성.
    현재 Django SensorDataView 가 power 를 수신하지 않으므로
    Phase E 에서는 생성만 하고 전송은 생략 (Phase F 정리 예정).
    """
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


def move_worker(worker: dict) -> None:
    """
    작업자 위치를 1틱 분 업데이트 (in-place).

    관성 있는 랜덤 워크 + 이미지 경계 bounce.
    """
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