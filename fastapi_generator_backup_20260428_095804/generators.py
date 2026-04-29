"""
generators.py — 센서값 / 작업자 위치 시뮬레이션 데이터 생성

[변경 이력]
  v1: i.i.d. 가우시안 + 글로벌 tick 기반 이벤트 (모든 센서 동시 점프)
  v2 (R1 — 가스 센서별 독립화 + 평균회귀):
    문제 (사진 진단): mixed 모드에서 tick % 30 == 0 같은 글로벌 트리거가
                     모든 센서를 동시에 caution 으로 점프시킴.
                     i.i.d. 가우시안은 임계 근처에서 빈번히 왔다 갔다.

    처방:
      A) 평균회귀 (OU 스타일) — 이전 값을 기억하고 center 로 천천히 끌림.
         매 틱 큰 점프 없음, 자연스러운 흐름.
         수식: new = prev + theta*(center - prev) + sigma*Z
      B) 센서별 독립 이벤트 — tick % 30 글로벌 트리거 제거.
         각 가스마다 매 틱 작은 확률 (1/주기) 로 이벤트 활성화 +
         일정 지속시간(N틱) 동안 caution 영역값 유지.
         센서마다 독립 random 호출 → 동시 발생 확률 거의 0.

    호출 시그니처 변경:
      generate_gas(tick, mode) → generate_gas(tick, mode, prev_state=None)
      prev_state: scheduler 가 device 별로 보관하는 dict.
                  - last_gas: dict | None  (이전 틱 가스값)
                  - events: dict[str, int] (이벤트별 잔여 틱수)
                  None 이면 첫 호출로 간주, normal center 로 시작.
                  in-place 변경 + 반환값 'gas' 사용 모두 지원.

  v3 (R1 확장 — 전력에도 동일 처방):
    문제: 사진에서 가스 정상화 후에도 power_01/02/03 가 같은 초에 동시 caution.
          generate_power 에 tick % 50 == 0 글로벌 트리거가 그대로 남아있었음.
    처방: generate_power 도 OU 평균회귀 + 센서별 독립 이벤트로 재작성.
          current/voltage 두 값에 OU 적용, watt = current * voltage 는 파생.
          이벤트는 "갑작 점프" 가 아니라 "천천히 18A 까지 상승" 형태
          (실제 산업현장 부하 변동 패턴에 가까움).
          시그니처 동일하게 prev_state=None 추가.

  v4 (Step B-1 — 카탈로그 측정 범위 정합):
    R&D 산출물 정합성 강화. 시뮬 측정 범위를 실제 센서 카탈로그 사양에 맞춤.
    출처: 유독가스 감지 시스템 카탈로그 (㈜에어위드) — Air Sensor Specification.
          R&D 계획서 SFR-001-01 (유해가스 탐지 센서 개발 요구사항).

    변경 항목 (max 값만, 분포는 OU 가 유지):
      CO   500 → 1,000 ppm
      CO2  10,000 → 40,000 ppm
      NO2  5 → 20 ppm
      SO2  10 → 20 ppm
      O3   0.5 → 10 ppm
      VOC  5 → 65 ppm
      (H2S 100, O2 25, NH3 100 은 카탈로그와 일치 — 변경 없음)

    임계치(GAS_THRESHOLDS) 는 변경 안 함 — KOSHA/ACGIH/NIOSH 산업안전 표준
    이라 측정 범위와 무관하게 유지. 시뮬 OU 분포도 그대로 유지(σ 작음).

  설계 원칙:
    상태(status) 판정은 Django SensorDataView 가 수행하므로 여기선 안 함.
"""

import math
import random


# ═══════════════════════════════════════════════════════════
# 가스 임계치 (KOSHA, ACGIH, NIOSH 기준)
# Django 쪽 판정과 반드시 일치해야 함
# ═══════════════════════════════════════════════════════════
GAS_THRESHOLDS = {
    "co": {"normal": 25, "danger": 200},
    "h2s": {"normal": 10, "danger": 50},
    "co2": {"normal": 1000, "danger": 5000},
    "o2": {"low": 18.0, "high": 23.5},
    "no2": {"normal": 3, "danger": 5},
    "so2": {"normal": 2, "danger": 5},
    "o3": {"normal": 0.05, "danger": 0.1},
    "nh3": {"normal": 25, "danger": 50},
    "voc": {"normal": 0.5, "danger": 2.0},
}

GAS_NORMAL_CENTER = {
    "co": 12,
    "h2s": 2,
    "co2": 600,
    "o2": 20.9,
    "no2": 0.04,
    "so2": 0.2,
    "o3": 0.02,
    "nh3": 8,
    "voc": 0.15,
}

# 작업자 이동 한계 (이미지 좌표계)
MARGIN = 40
IMG_W = 1360
IMG_H = 960


# ═══════════════════════════════════════════════════════════
# OU(Ornstein-Uhlenbeck) 평균회귀 파라미터
# ═══════════════════════════════════════════════════════════
#
# theta: 평균 회귀 강도. 작을수록 이전 값에 가까이 머물고 천천히 표류.
#        0.08 ≒ 약 12틱 (≈12초) 의 시정수 — 사람 눈에 "흐른다" 로 보이는 속도
# sigma: 가우시안 노이즈 std. v1 대비 약 2/3 수준으로 축소 (점프 방지)
# clamp_min/max: **유독가스 감지 시스템 카탈로그(㈜에어위드)의 측정 범위 사양** 과 일치 (B-1).
#                실제 분포는 σ 가 작아 max 근처까지 튀지 않으나,
#                센서 사양과 일치시켜 R&D 산출물 정합성 확보.
GAS_OU_PARAMS = {
    "co": {"theta": 0.08, "sigma": 1.0, "min": 0, "max": 1000},  # 카탈로그: 0~1,000 ppm
    "h2s": {"theta": 0.08, "sigma": 0.3, "min": 0, "max": 100},  # 카탈로그: 0~100 ppm
    "co2": {
        "theta": 0.08,
        "sigma": 25,
        "min": 300,
        "max": 40000,
    },  # 카탈로그: 0~40,000 ppm
    "o2": {"theta": 0.10, "sigma": 0.08, "min": 15, "max": 25},  # 카탈로그: 0~25 %
    "no2": {"theta": 0.08, "sigma": 0.005, "min": 0, "max": 20},  # 카탈로그: 0~20 ppm
    "so2": {"theta": 0.08, "sigma": 0.02, "min": 0, "max": 20},  # 카탈로그: 0~20 ppm
    "o3": {"theta": 0.08, "sigma": 0.002, "min": 0, "max": 10},  # 카탈로그: 0~10 ppm
    "nh3": {"theta": 0.08, "sigma": 0.7, "min": 0, "max": 100},  # 카탈로그: 0~100 ppm
    "voc": {"theta": 0.08, "sigma": 0.012, "min": 0, "max": 65},  # 카탈로그: 0~65 ppm
}

# ═══════════════════════════════════════════════════════════
# mixed 모드 — 센서별 독립 이벤트 정의
# ═══════════════════════════════════════════════════════════
#
# 매 틱 prob 확률로 이벤트 발생. 발생 시 duration 틱 동안 center_when_active
# 부근으로 평균회귀 (caution 영역).
# v1 의 글로벌 tick % N 트리거를 매 틱 독립 확률로 분산:
#   tick % 30 == 0  → prob = 1/30 ≒ 3.3%
#   tick % 60 == 0  → prob = 1/60 ≒ 1.7%
#   ...
# 이렇게 분산하면 long-run 평균 발생 빈도는 v1 과 동등하지만
# 모든 센서가 동시에 발생할 확률은 (3.3%)^4 ≒ 0.0001%.
GAS_EVENTS = {
    "co": {"prob": 1 / 45, "duration": 6, "active_center": 32, "active_sigma": 3},
    "h2s": {"prob": 1 / 60, "duration": 6, "active_center": 18, "active_sigma": 2},
    "o2": {"prob": 1 / 45, "duration": 6, "active_center": 16.5, "active_sigma": 0.6},
    "voc": {"prob": 1 / 45, "duration": 4, "active_center": 0.7, "active_sigma": 0.08},
    "nh3": {"prob": 1 / 60, "duration": 6, "active_center": 35, "active_sigma": 3},
}


def gauss(center: float, std: float, min_val: float, max_val: float) -> float:
    """박스-뮬러 변환 기반 정규분포 샘플, min/max 클램핑."""
    z = math.sqrt(-2 * math.log(max(1e-10, random.random()))) * math.cos(
        2 * math.pi * random.random()
    )
    return min(max_val, max(min_val, center + z * std))


def _ou_step(
    prev: float,
    center: float,
    theta: float,
    sigma: float,
    min_val: float,
    max_val: float,
) -> float:
    """
    OU(평균회귀) 한 틱.
        new = prev + theta*(center - prev) + sigma*Z
    Z ~ N(0,1). 결과는 [min_val, max_val] 로 클램프.
    """
    z = math.sqrt(-2 * math.log(max(1e-10, random.random()))) * math.cos(
        2 * math.pi * random.random()
    )
    nxt = prev + theta * (center - prev) + sigma * z
    return min(max_val, max(min_val, nxt))


def generate_gas(
    tick: int, mode: str = "mixed", prev_state: dict | None = None
) -> dict:
    """
    9종 가스 측정값 1틱 분 생성. 평균회귀 + 센서별 독립 이벤트.

    Args:
        tick: 시뮬레이션 틱 카운터 (현재는 로그용, 로직에선 안 씀).
        mode: "normal" | "mixed" | "danger"
        prev_state: 호출자(scheduler) 가 device 별로 보관하는 상태 dict.
            {"last_gas": dict | None, "events": dict[str, int]}
            None 또는 빈 dict 이면 normal center 로 시작.
            **in-place 로 갱신됨** (last_gas, events 필드).

    Returns:
        {"co": float, "h2s": float, ..., "voc": float}
    """
    # ─── 상태 dict 정규화 ───
    if prev_state is None:
        prev_state = {}
    prev_gas: dict | None = prev_state.get("last_gas")
    events: dict[str, int] = prev_state.setdefault("events", {})

    # ─── danger 모드: 모든 가스가 임계 위로 결정적 위험값 (랜덤워크 무시) ───
    # 각 가스의 GAS_THRESHOLDS['danger'] 임계를 명확히 초과하도록 정규화.
    # 사진 진단 (B-1 후속 발견): NO2/SO2/O3/NH3 가 danger 모드에서도 normal 분포로
    # 생성되어 "위험 시나리오인데 일부 가스만 위험" 으로 표시되던 문제 해결.
    if mode == "danger":
        g = {
            "co": 200 + random.random() * 150,  # caution 25, danger 200 → 200~350
            "h2s": 50 + random.random() * 30,  # caution 10, danger 50  → 50~80
            "co2": 5000
            + random.random() * 3000,  # caution 1000, danger 5000 → 5000~8000
            "o2": 12
            + random.random()
            * 3.5,  # 저산소 위험 (caution 18, danger 16 미만) → 12~15.5
            "no2": 5.0 + random.random() * 3,  # caution 3, danger 5 → 5~8 (B-1 후속)
            "so2": 5.0 + random.random() * 3,  # caution 2, danger 5 → 5~8 (B-1 후속)
            "o3": 0.1
            + random.random() * 0.1,  # caution 0.05, danger 0.1 → 0.1~0.2 (B-1 후속)
            "nh3": 50
            + random.random() * 30,  # caution 25, danger 50 → 50~80 (B-1 후속)
            "voc": 2.0 + random.random() * 2,  # caution 0.5, danger 2.0 → 2~4
        }
        # danger 모드에선 events 리셋 (mixed 로 돌아갈 때 깔끔)
        prev_state["events"] = {}
        prev_state["last_gas"] = _round_gas(g)
        return prev_state["last_gas"]

    # ─── normal / mixed 공통: OU 평균회귀로 한 틱 ───
    g: dict = {}
    for key, params in GAS_OU_PARAMS.items():
        # 이벤트 활성 중이면 center 를 caution 쪽으로 올림
        is_event_active = mode == "mixed" and events.get(key, 0) > 0
        if is_event_active:
            ev = GAS_EVENTS[key]
            target_center = ev["active_center"]
            sigma = ev["active_sigma"]
            events[key] -= 1  # 잔여 틱 감소
        else:
            target_center = GAS_NORMAL_CENTER[key]
            sigma = params["sigma"]

        # 첫 호출 — prev 없으면 normal center 에서 시작
        prev_val = prev_gas[key] if prev_gas is not None else GAS_NORMAL_CENTER[key]

        g[key] = _ou_step(
            prev=prev_val,
            center=target_center,
            theta=params["theta"],
            sigma=sigma,
            min_val=params["min"],
            max_val=params["max"],
        )

    # ─── mixed 모드: 새 이벤트 트리거 (센서별 독립) ───
    if mode == "mixed":
        for key, ev in GAS_EVENTS.items():
            # 이미 활성 중이면 재트리거 안 함 (중첩 방지)
            if events.get(key, 0) > 0:
                continue
            if random.random() < ev["prob"]:
                events[key] = ev["duration"]
                # 이벤트 시작 직후 한 틱은 즉시 active_center 로 점프하지 않고,
                # OU 가 다음 호출부터 끌어당김 — 자연스러운 상승 곡선

    # ─── 상태 보존 + 반환 ───
    rounded = _round_gas(g)
    prev_state["last_gas"] = rounded
    return rounded


def _round_gas(g: dict) -> dict:
    """자릿수 정리 — 표시 일관성 유지."""
    return {
        "co": round(g["co"], 2),
        "h2s": round(g["h2s"], 2),
        "co2": round(g["co2"], 1),
        "o2": round(g["o2"], 1),
        "no2": round(g["no2"], 3),
        "so2": round(g["so2"], 2),
        "o3": round(g["o3"], 3),
        "nh3": round(g["nh3"], 1),
        "voc": round(g["voc"], 2),
    }


# ═══════════════════════════════════════════════════════════
# Layer 3 — 알람 메시지용 worst 항목 식별 헬퍼
# ═══════════════════════════════════════════════════════════
#
# scheduler 가 알람 detail 라벨에 "실제로 임계 넘긴 가스/항목" 을 박기 위해 사용.
# Django 측 classify_gas / classify_power 와 임계치 일치 필수 (GAS_THRESHOLDS 참조).
#
# 반환 형식: (label_kr, value) — 예: ("CO", 43.83) / ("H2S", 18.2) / ("전류", 22.5)
# 임계치 미초과 시: (None, None) — 호출자가 fallback 처리

# 표시용 한국어 라벨 매핑
GAS_LABELS = {
    "co": "CO",
    "h2s": "H2S",
    "co2": "CO2",
    "o2": "O2",
    "no2": "NO2",
    "so2": "SO2",
    "o3": "O3",
    "nh3": "NH3",
    "voc": "VOC",
}


def identify_worst_gas(gas: dict) -> tuple[str | None, float | None]:
    """
    가스 측정값 9종 중 **임계치 대비 가장 위험한 항목** 의 (라벨, 값) 반환.

    "위험 정도" = (값 - caution 임계) / (danger 임계 - caution 임계)
    - O2 는 양방향 (저산소/고산소 둘 다 위험)
    - 나머지 8종은 단방향 (값 ≥ 임계 → 위험)

    Returns:
        (label, value) — 예: ("H2S", 18.2)
        (None, None)   — 모든 가스가 normal 영역일 때
    """
    worst_score = -1.0
    worst_key = None

    for key, val in gas.items():
        if val is None:
            continue
        v = float(val)

        if key == "o2":
            if v < 18:
                score = (18 - v) / 2.0  # 18 → 0점, 16 → 1점
            elif v > 21.5:
                score = (v - 21.5) / 2.0
            else:
                continue
        else:
            t = GAS_THRESHOLDS.get(key)
            if not t or "normal" not in t:
                continue
            caution_th = t["normal"]
            danger_th = t["danger"]
            if v < caution_th:
                continue
            score = (v - caution_th) / max(danger_th - caution_th, 0.001)

        if score > worst_score:
            worst_score = score
            worst_key = key

    if worst_key is None:
        return None, None
    return GAS_LABELS[worst_key], gas[worst_key]


def identify_worst_power(power: dict) -> tuple[str | None, float | None]:
    """
    전력 측정값 중 **임계치 대비 가장 위험한 항목** 의 (라벨, 값) 반환.

    Note: 전력은 동적 임계(24h 중앙값) 라 정확한 판정은 Django 만 가능.
          여기선 정상 운전 평균 대비 비율로 근사.

    Returns:
        (label, value) — 예: ("전류", 22.57)
        (None, None)   — 모든 항목이 정상 영역일 때
    """
    NORMAL_CURRENT = 12.0  # POWER_OU_PARAMS center 와 일치
    NORMAL_VOLTAGE = 220.0
    CURRENT_CAUTION_RATIO = 1.5  # 동적 임계 근사 (18A)

    worst_score = -1.0
    worst_key = None

    cur = power.get("current")
    if cur is not None and cur >= NORMAL_CURRENT * CURRENT_CAUTION_RATIO:
        score = (cur - NORMAL_CURRENT * CURRENT_CAUTION_RATIO) / NORMAL_CURRENT
        if score > worst_score:
            worst_score = score
            worst_key = "current"

    volt = power.get("voltage")
    if volt is not None:
        deviation = abs(volt - NORMAL_VOLTAGE) / NORMAL_VOLTAGE
        if deviation >= 0.05:  # 산업 전기설비 ±5% 이탈
            score = (deviation - 0.05) / 0.05
            if score > worst_score:
                worst_score = score
                worst_key = "voltage"

    if worst_key == "current":
        return "전류", power["current"]
    elif worst_key == "voltage":
        return "전압", power["voltage"]
    return None, None


# ═══════════════════════════════════════════════════════════
# 전력 OU 파라미터 + 이벤트 정의 (R1 v3)
# ═══════════════════════════════════════════════════════════
#
# 정상 운전: current 12 ± 2A, voltage 220 ± 3V.
# 이벤트 활성: current 18A 부근으로 평균회귀 (caution 영역).
#   동적 임계치(평소 12A 의 1.5x = 18A) 가 caution 으로 잡는 영역.
# voltage 는 이벤트 영향 안 받음 — 실제 산업현장에선 전류 변동이 우선.
POWER_OU_PARAMS = {
    "current": {"theta": 0.10, "sigma": 0.6, "min": 0, "max": 50, "center": 12},
    "voltage": {"theta": 0.10, "sigma": 1.5, "min": 190, "max": 250, "center": 220},
}

# 매 틱 prob 확률로 이벤트 발생. duration 틱 동안 active_center 부근 유지.
# v1 의 tick % 50 == 0 → prob = 1/50 = 2% 로 분산.
POWER_EVENTS = {
    "current": {
        "prob": 1 / 50,
        "duration": 6,
        "active_center": 18,
        "active_sigma": 0.8,
    },
}


def generate_power(
    tick: int, mode: str = "mixed", prev_state: dict | None = None
) -> dict:
    """
    전력 데이터 1틱 분 생성. OU 평균회귀 + 센서별 독립 이벤트 (R1 v3).

    Args:
        tick: 시뮬레이션 틱 카운터 (현재는 로그용).
        mode: "normal" | "mixed" | "danger"
        prev_state: 호출자(scheduler) 가 device 별로 보관하는 상태 dict.
            {"last_power": dict | None, "events": dict[str, int]}
            None 또는 빈 dict 이면 normal center 로 시작.
            **in-place 로 갱신됨**.

    Returns:
        {"current": float, "voltage": float, "watt": float}
    """
    # ─── 상태 dict 정규화 ───
    if prev_state is None:
        prev_state = {}
    prev_power: dict | None = prev_state.get("last_power")
    events: dict[str, int] = prev_state.setdefault("events", {})

    # ─── danger 모드: 결정적 위험값 (랜덤워크 무시) ───
    if mode == "danger":
        current = 30 + random.random() * 15
        voltage = 195 + random.random() * 10
        result = {
            "current": round(current, 2),
            "voltage": round(voltage, 2),
            "watt": round(current * voltage, 1),
        }
        prev_state["events"] = {}
        prev_state["last_power"] = result
        return result

    # ─── normal / mixed 공통: OU 평균회귀로 한 틱 ───
    out: dict = {}
    for key, params in POWER_OU_PARAMS.items():
        # 이벤트 활성 중인지 (current 만 이벤트 영향)
        is_event_active = (
            mode == "mixed" and key in POWER_EVENTS and events.get(key, 0) > 0
        )
        if is_event_active:
            ev = POWER_EVENTS[key]
            target_center = ev["active_center"]
            sigma = ev["active_sigma"]
            events[key] -= 1
        else:
            target_center = params["center"]
            sigma = params["sigma"]

        # 첫 호출 — prev 없으면 center 에서 시작
        prev_val = prev_power[key] if prev_power is not None else params["center"]

        out[key] = _ou_step(
            prev=prev_val,
            center=target_center,
            theta=params["theta"],
            sigma=sigma,
            min_val=params["min"],
            max_val=params["max"],
        )

    # ─── mixed 모드: 새 이벤트 트리거 (센서별 독립) ───
    if mode == "mixed":
        for key, ev in POWER_EVENTS.items():
            if events.get(key, 0) > 0:
                continue  # 이미 활성 — 중첩 방지
            if random.random() < ev["prob"]:
                events[key] = ev["duration"]

    # ─── watt 파생 + 자릿수 정리 ───
    result = {
        "current": round(out["current"], 2),
        "voltage": round(out["voltage"], 2),
        "watt": round(out["current"] * out["voltage"], 1),
    }
    prev_state["last_power"] = result
    return result


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
