"""
scenario.py — R&D 시나리오 토글 상태 + Phase 자동 ramp + 데이터 생성

[5차 세션 C′-3b-2 (b) 단계 — SCENARIO_DESIGN_v2_1.md 기반]

5 device 토글 ON/OFF 로 6-phase 시계열 자동 ramp:
  phase 0 정상 → 1 전조 → 2 주의 → 3 위험 → 4 조치 → 5 복귀

매핑 (고정):
  sensor_01 → G3 H2S 누출
  sensor_02 → G4 CO 연소이상 (CO + O2 + CO2)
  sensor_03 → G1 환기 불량 (CO2 + O2 + VOC)
  power_01  → P1 단일 채널 과부하 (current + watt)
  power_02  → P3 전압 강하 (voltage + current)

토글 우위:
  - 매핑된 5 device 는 레거시 모드 (normal/mixed/danger) 무시
  - 토글 OFF 라도 phase 0 (정상 baseline) 으로 라벨 동봉
  - 비매핑 device (sensor_04~07, power_03) 는 레거시 모드 fallback,
    라벨은 scenario_id="legacy:<mode>", expected_* = null

비영향 채널:
  토글된 device 의 시나리오와 무관한 가스/전력 필드는 baseline + OU 노이즈

Phase 전환 규칙 (현재 phase + 토글 방향으로 결정):
  | 현재 phase | 토글 ON   | 토글 OFF |
  | 0          | → 1       | 머묾    |
  | 1          | → 2 (30s) | → 5    |
  | 2          | → 3 (30s) | → 5    |
  | 3          | → 4 (30s) | → 5    |
  | 4          | 머묾 peak | → 5    |
  | 5          | → 1 재개  | → 0    |
"""
from __future__ import annotations

import math
import random
import time


# ═══════════════════════════════════════════════════════════
# 매핑 / 상수
# ═══════════════════════════════════════════════════════════

# device_id → (scenario_id, sensor_type)
SCENARIO_DEVICE_MAP: dict[str, tuple[str, str]] = {
    "sensor_01": ("G3", "gas"),
    "sensor_02": ("G4", "gas"),
    "sensor_03": ("G1", "gas"),
    "power_01":  ("P1", "power"),
    "power_02":  ("P3", "power"),
}

PHASE_DURATION_GAS_SEC   = 30
PHASE_DURATION_POWER_SEC = 120

# Phase → expected_status 라벨
PHASE_STATUS = {
    0: "normal",   # 정상
    1: "normal",   # 전조 (★ 라벨은 normal — AI 가 잡으면 lead-time 보너스)
    2: "caution",  # 주의
    3: "danger",   # 위험
    4: "danger",   # 조치 (peak)
    5: "normal",   # 복귀
}


# ═══════════════════════════════════════════════════════════
# Phase 별 target (μ, σ) — v2.1 §10 표 인코딩
# ═══════════════════════════════════════════════════════════

# G3 — sensor_01 — H2S 누출 (H2S 만 변화, 나머지 baseline)
G3_PHASES = [
    {"h2s": (3.1, 1.5)},     # 0 정상
    {"h2s": (7,   2)},       # 1 전조
    {"h2s": (18,  3)},       # 2 주의
    {"h2s": (65,  8)},       # 3 위험
    {"h2s": (70,  8)},       # 4 조치
    {"h2s": (8,   3)},       # 5 복귀
]

# G4 — sensor_02 — CO 연소이상 (CO + O2 + CO2)
G4_PHASES = [
    {"co": (14.5, 3),   "o2": (20.9, 0.1), "co2": (600,  60) },   # 0
    {"co": (21,   4),   "o2": (20.5, 0.2), "co2": (750,  70) },   # 1
    {"co": (45,   6),   "o2": (19.8, 0.3), "co2": (950,  90) },   # 2
    {"co": (280, 30),   "o2": (18.5, 0.4), "co2": (1400, 150)},   # 3
    {"co": (320, 30),   "o2": (18.0, 0.4), "co2": (1500, 150)},   # 4
    {"co": (60,  10),   "o2": (19.5, 0.3), "co2": (900,  100)},   # 5
]

# G1 — sensor_03 — 환기 불량 (CO2 + O2 + VOC)
G1_PHASES = [
    {"co2": (600,  60),  "o2": (20.9, 0.1), "voc": (0.18, 0.1) },   # 0
    {"co2": (850,  80),  "o2": (20.5, 0.2), "voc": (0.35, 0.15)},   # 1
    {"co2": (1200, 100), "o2": (19.5, 0.3), "voc": (0.65, 0.2) },   # 2
    {"co2": (3500, 300), "o2": (17.5, 0.5), "voc": (1.2,  0.3) },   # 3
    {"co2": (3800, 300), "o2": (17.0, 0.5), "voc": (1.4,  0.3) },   # 4
    {"co2": (1500, 200), "o2": (19.0, 0.4), "voc": (0.7,  0.2) },   # 5
]

PHASE_TARGETS_GAS: dict[str, list[dict]] = {
    "G3": G3_PHASES, "G4": G4_PHASES, "G1": G1_PHASES,
}

# P1 — power_01 — 단일 채널 과부하
P1_PHASES = [
    {"current": (10, 2), "voltage": (220, 2), "watt": (2200,  400 )},   # 0
    {"current": (18, 3), "voltage": (219, 2), "watt": (3940,  600 )},   # 1
    {"current": (35, 4), "voltage": (217, 3), "watt": (7600,  900 )},   # 2
    {"current": (85, 8), "voltage": (213, 4), "watt": (18000, 1700)},   # 3
    {"current": (95, 8), "voltage": (211, 4), "watt": (20000, 1700)},   # 4
    {"current": (25, 4), "voltage": (218, 2), "watt": (5450,  900 )},   # 5
]

# P3 — power_02 — 전압 강하 (sag)
P3_PHASES = [
    {"voltage": (220, 2), "current": (10, 2), "watt": (2200, 400)},   # 0
    {"voltage": (213, 3), "current": (11, 2), "watt": (2350, 450)},   # 1
    {"voltage": (200, 4), "current": (13, 2), "watt": (2600, 500)},   # 2
    {"voltage": (175, 6), "current": (16, 3), "watt": (2800, 550)},   # 3
    {"voltage": (170, 6), "current": (17, 3), "watt": (2890, 550)},   # 4
    {"voltage": (205, 3), "current": (12, 2), "watt": (2460, 450)},   # 5
]

PHASE_TARGETS_POWER: dict[str, list[dict]] = {
    "P1": P1_PHASES, "P3": P3_PHASES,
}


# 비영향 가스 채널 baseline (μ, σ) — v2.1 §9 실측 분포
GAS_BASELINE = {
    "co":  (14.5, 3   ),
    "h2s": (3.1,  1.5 ),
    "co2": (600,  60  ),
    "o2":  (20.9, 0.1 ),
    "nh3": (10,   4   ),
    "no2": (0.04, 0.02),
    "so2": (0.19, 0.07),
    "o3":  (0.02, 0.01),
    "voc": (0.18, 0.1 ),
}


# ═══════════════════════════════════════════════════════════
# OU 평균회귀
# ═══════════════════════════════════════════════════════════

THETA = 0.3   # 회귀 속도. 0.3 ≈ 3틱 정도면 새 center 근처 도달

def _ou_step(prev: float, center: float, sigma: float,
             min_val: float = 0.0, max_val: float | None = None) -> float:
    """OU 한 틱 — new = prev + theta*(center - prev) + sigma*Z."""
    z = math.sqrt(-2 * math.log(max(1e-10, random.random()))) \
        * math.cos(2 * math.pi * random.random())
    nxt = prev + THETA * (center - prev) + sigma * z
    if max_val is not None:
        nxt = min(max_val, nxt)
    return max(min_val, nxt)


# ═══════════════════════════════════════════════════════════
# ScenarioState — in-memory 토글 + phase 추적
# ═══════════════════════════════════════════════════════════

class ScenarioState:
    """
    5 device 의 토글 / phase 상태를 in-memory 로 유지.
    FastAPI 재시작 시 초기화 (전 device 토글 OFF, phase 0).
    """

    def __init__(self):
        # device_id → {"on": bool, "current_phase": int, "phase_started_at": float}
        self._toggles: dict[str, dict] = {}

    # ─── 토글 ───
    def toggle(self, device_id: str, state: bool) -> dict:
        if device_id not in SCENARIO_DEVICE_MAP:
            return {
                "ok": False,
                "error": f"device_id {device_id} is not a mapped scenario device",
                "valid": sorted(SCENARIO_DEVICE_MAP.keys()),
            }

        now = time.time()
        existing = self._toggles.get(device_id, {
            "on": False, "current_phase": 0, "phase_started_at": now,
        })
        current_phase = existing["current_phase"]

        # ─── ON ───
        if state:
            if current_phase == 0 or current_phase == 5:
                next_phase = 1   # phase 0 또는 5 (복귀 중) → phase 1 시작
            elif current_phase == 4:
                next_phase = 4   # peak 유지
            else:
                next_phase = current_phase   # 1~3 진행 중 → 그대로
            self._toggles[device_id] = {
                "on": True,
                "current_phase": next_phase,
                "phase_started_at": now if next_phase != current_phase else existing["phase_started_at"],
            }
        # ─── OFF ───
        else:
            if current_phase == 0:
                # 이미 정상 — 변화 없음
                self._toggles[device_id] = {
                    "on": False, "current_phase": 0, "phase_started_at": now,
                }
            else:
                # 어떤 phase 든 → 5 복귀 진입
                self._toggles[device_id] = {
                    "on": False, "current_phase": 5, "phase_started_at": now,
                }

        return {"ok": True, "device_id": device_id, **self._toggles[device_id]}

    # ─── phase 자동 ramp ───
    def get_phase(self, device_id: str, now: float | None = None) -> int:
        """
        현재 phase 를 반환하고, 시간 경과 시 다음 phase 로 in-place ramp.
        매핑 안 된 device 면 0 반환.
        """
        if device_id not in SCENARIO_DEVICE_MAP:
            return 0
        if device_id not in self._toggles:
            return 0

        if now is None:
            now = time.time()

        state = self._toggles[device_id]
        current_phase = state["current_phase"]
        phase_started = state["phase_started_at"]

        _, sensor_type = SCENARIO_DEVICE_MAP[device_id]
        phase_dur = (PHASE_DURATION_GAS_SEC if sensor_type == "gas"
                     else PHASE_DURATION_POWER_SEC)

        if now - phase_started < phase_dur:
            return current_phase   # 아직 같은 phase

        # 시간 만료 — 다음 phase 진행
        if state["on"]:
            # ON 모드: 1 → 2 → 3 → 4 (4 stay)
            if current_phase < 4:
                state["current_phase"] = current_phase + 1
                state["phase_started_at"] = now
        else:
            # OFF 모드: 5 → 0 (0 stay)
            if current_phase == 5:
                state["current_phase"] = 0
                state["phase_started_at"] = now

        return state["current_phase"]

    # ─── 일괄 OFF (phase 0 즉시 리셋) ───
    def clear_all(self) -> int:
        n = sum(1 for t in self._toggles.values() if t["on"])
        now = time.time()
        for device_id in SCENARIO_DEVICE_MAP:
            self._toggles[device_id] = {
                "on": False, "current_phase": 0, "phase_started_at": now,
            }
        return n

    # ─── 상태 조회 ───
    def state(self) -> dict:
        now = time.time()
        devices = {}
        for device_id, (scenario_id, _) in SCENARIO_DEVICE_MAP.items():
            t = self._toggles.get(device_id, {
                "on": False, "current_phase": 0, "phase_started_at": now,
            })
            phase = self.get_phase(device_id, now)
            elapsed = int(now - t["phase_started_at"])
            devices[device_id] = {
                "on": t["on"],
                "phase": phase,
                "elapsed_in_phase_sec": elapsed,
                "scenario_id": scenario_id,
            }
        return {
            "phase_duration": {
                "gas":   PHASE_DURATION_GAS_SEC,
                "power": PHASE_DURATION_POWER_SEC,
            },
            "devices": devices,
        }

    # ─── 라벨 (POST payload 동봉용) ───
    def get_labels(self, device_id: str) -> dict:
        """
        매핑된 device → 실제 phase / scenario_id / status 라벨
        매핑 안 된 device → 모두 None (호출자가 legacy 라벨 채움)
        """
        if device_id not in SCENARIO_DEVICE_MAP:
            return {"scenario_id": None, "expected_phase": None, "expected_status": None}

        scenario_id, _ = SCENARIO_DEVICE_MAP[device_id]
        phase = self.get_phase(device_id)
        return {
            "scenario_id": scenario_id,
            "expected_phase": phase,
            "expected_status": PHASE_STATUS[phase],
        }

    def is_mapped(self, device_id: str) -> bool:
        return device_id in SCENARIO_DEVICE_MAP


# ═══════════════════════════════════════════════════════════
# Phase 기반 데이터 생성 — generators.py 와 별도 path
# ═══════════════════════════════════════════════════════════

def generate_scenario_gas(device_id: str, phase: int,
                          prev_gas: dict | None) -> dict | None:
    """
    매핑된 가스 sensor 의 phase 기반 9 가스 1틱 생성.
    영향 채널은 phase target μ, σ. 비영향 채널은 baseline.
    """
    if device_id not in SCENARIO_DEVICE_MAP:
        return None
    scenario_id, sensor_type = SCENARIO_DEVICE_MAP[device_id]
    if sensor_type != "gas":
        return None
    if scenario_id not in PHASE_TARGETS_GAS:
        return None

    targets = PHASE_TARGETS_GAS[scenario_id][phase]
    g: dict = {}

    for key, (base_center, base_sigma) in GAS_BASELINE.items():
        if key in targets:
            center, sigma = targets[key]
        else:
            center, sigma = base_center, base_sigma
        prev_val = prev_gas.get(key, center) if prev_gas else center
        # 가스별 적정 max
        max_v = {"co": 1000, "h2s": 100, "co2": 40000, "o2": 25,
                 "nh3": 100, "no2": 20, "so2": 20, "o3": 10, "voc": 65}.get(key)
        g[key] = _ou_step(prev_val, center, sigma, min_val=0.0, max_val=max_v)

    return {
        "co":  round(g["co"],  2),
        "h2s": round(g["h2s"], 2),
        "co2": round(g["co2"]   ),
        "o2":  round(g["o2"],  2),
        "no2": round(g["no2"], 3),
        "so2": round(g["so2"], 3),
        "o3":  round(g["o3"],  3),
        "nh3": round(g["nh3"], 2),
        "voc": round(g["voc"], 3),
    }


def generate_scenario_power(device_id: str, phase: int,
                            prev_power: dict | None) -> dict | None:
    """매핑된 전력 device 의 phase 기반 3 필드 1틱 생성."""
    if device_id not in SCENARIO_DEVICE_MAP:
        return None
    scenario_id, sensor_type = SCENARIO_DEVICE_MAP[device_id]
    if sensor_type != "power":
        return None
    if scenario_id not in PHASE_TARGETS_POWER:
        return None

    targets = PHASE_TARGETS_POWER[scenario_id][phase]
    p: dict = {}
    for key in ("current", "voltage", "watt"):
        center, sigma = targets[key]
        prev_val = prev_power.get(key, center) if prev_power else center
        max_v = {"current": 200, "voltage": 280, "watt": 50000}.get(key)
        p[key] = _ou_step(prev_val, center, sigma, min_val=0.0, max_val=max_v)

    return {
        "current": round(p["current"], 2),
        "voltage": round(p["voltage"], 1),
        "watt":    round(p["watt"]),
    }
