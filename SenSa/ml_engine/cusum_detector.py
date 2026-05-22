"""
ml_engine/cusum_detector.py — CUSUM 드리프트 탐지

천천히 누적되는 가스 농도 상승/하강을 감지.
Z-score/ChangePoint가 못 잡는 완만한 드리프트 전용.

알고리즘 (CUSUM — Cumulative Sum):
  초기 BASELINE_POINTS 개로 기준 평균(μ)·표준편차(σ) 산출.
  이후 매 틱:
    S_high[t] = max(0, S_high[t-1] + (x - μ - k))   ← 상향 드리프트 누적
    S_low[t]  = max(0, S_low[t-1]  + (μ - k - x))   ← 하향 드리프트 누적
    k = K_SIGMA × σ   (자연 변동 허용폭, 이 안의 변화는 무시)
    S > h = H_SIGMA × σ → DRIFT_ALERT

파라미터 근거:
  K_SIGMA=0.5, H_SIGMA=4.0 — 표준 CUSUM 설계점.
  δ=1σ 크기의 드리프트를 평균 8.5틱 만에 감지 (ARL₁ ≈ 8.5).
  무드리프트(정상) 상태에서 오탐 ARL₀ ≈ 370 틱.

알람 발생 후 S를 0으로 리셋 → 다음 드리프트 즉시 감지 가능.
60초 중복 억제는 devices/views.py _maybe_create_alarm 이 담당.

[baseline 주기 재산출]
  초기 설계에서는 BASELINE_POINTS 개 수집 후 μ/σ를 한 번만 고정.
  장기 운영 시 가스 환경(계절·공정 변화)이 달라지면 baseline이 구식이 되어
  드리프트를 못 잡거나 정상 구간에서 오탐이 발생.
  → REBASELINE_TICKS 틱마다 최근 BASELINE_POINTS 개 평균으로 재산출.
  재산출 시 S도 0으로 리셋하여 새 baseline 기준 누적 시작.
"""
import threading
from statistics import mean, stdev
from . import model_store

BASELINE_POINTS   = 20   # 기준 μ/σ 산출에 사용할 포인트 수
REBASELINE_TICKS  = 200  # N 틱마다 baseline 재산출 (500→200: 약 3분20초, 환경 변화 반응 속도 향상)
K_SIGMA = 0.5            # 허용 자연변동 계수 (모든 가스 동일 — 표준 CUSUM 설계점)
H_SIGMA = 4.0            # 기본 알람 임계 계수 (미등록 메트릭·전력 센서 fallback)
EPS = 1e-9

# ── 가스별 H_SIGMA (알람 임계 계수) ────────────────────────────────────────────
# 설계 근거:
#   H_SIGMA 가 낮을수록 더 민감 (작은 누적 드리프트에 반응) → 생명 위협 속도 빠른 가스
#   H_SIGMA 가 높을수록 덜 민감 → 완만하게 축적되거나 정상 변동폭이 큰 가스
#
#   gas   caution→danger 비율  특성              → H 선택 근거
#   h2s   10→50  (5×)          즉각 생명 위협    → 2.5 (가장 민감)
#   no2   3→5   (1.67×)        좁은 위험 구간    → 3.0
#   so2   2→5   (2.5×)         좁은 위험 구간    → 3.0
#   o3    0.05→0.1 (2×)        절대값 매우 작음  → 3.0
#   o2    18→16 / 21.5→23.5   양방향 임계       → 3.0
#   co    25→200 (8×)          중간 속도         → 4.0 (기본값)
#   nh3   25→50  (2×)          중간 속도         → 4.0
#   voc   0.5→2.0 (4×)         중간 속도         → 4.0
#   co2   1000→5000 (5×)       매우 완만한 누적  → 5.0 (FP 최소화)
#
# 전력(current/voltage/watt) 및 미등록 메트릭 → H_SIGMA(기본값=4.0) 사용
_GAS_H_SIGMA: dict[str, float] = {
    'h2s': 2.5,
    'no2': 3.0,
    'so2': 3.0,
    'o3':  3.0,
    'o2':  3.0,
    'co':  4.0,
    'nh3': 4.0,
    'voc': 4.0,
    'co2': 5.0,
}

# 절대값 게이트 비율
# 일반 가스: 현재값이 caution 임계치의 이 비율 미만이면 안전 구간으로 판단 → 알람 억제
# O2 (lower_is_worse): 현재값이 caution 임계치의 (1 + _O2_GATE_MARGIN) 배 초과면 안전 구간
_GATE_RATIO     = 0.6   # 일반 가스용
_O2_GATE_MARGIN = 0.1   # O2용 (caution×1.1 초과 = 안전)

_lock = threading.Lock()
_state: dict[str, dict] = {}


def _get_or_init(key: str) -> dict:
    if key not in _state:
        _state[key] = {
            "baseline_buf": [],
            "mu": None,
            "sigma": None,
            "S_high": 0.0,
            "S_low": 0.0,
            "tick": 0,
            "recent_buf": [],
        }
    else:
        # 이전 버전 상태에 새 필드 없으면 보완 (서버 재시작 없이 업그레이드 대응)
        st = _state[key]
        st.setdefault("tick", 0)
        st.setdefault("recent_buf", [])
    return _state[key]


def detect_drift(
    device_id: str,
    metric: str,
    value: float,
    caution_th: float | None = None,
    lower_is_worse: bool = False,
) -> dict:
    """
    CUSUM 드리프트 탐지.

    Args:
        device_id / metric: 상태 캐시 키 (센서·가스 종류별 독립 추적)
        value:              현재 측정값
        caution_th:         주의 임계치 (절대값 게이트용). None 이면 게이트 비활성.
        lower_is_worse:     True = O2처럼 값이 낮을수록 위험 (게이트 방향 반전).

    절대값 게이트 동작:
        안전 구간에서는 detected=False 를 반환하지만 S(누적합)는 리셋하지 않음.
        → 값이 위험 구간에 진입하는 순간 S가 이미 쌓여있어 즉시 알람 가능.
        S는 실제 알람이 발화될 때(=alarm_zone 진입 + S>h)만 리셋.

    Returns:
        {
          "detected":  bool,
          "S_high":    float,       # 상향 누적합 (게이트 억제 시 현재 누적값)
          "S_low":     float,       # 하향 누적합
          "direction": "up"|"down"|"",
          "mu":        float|None,  # 기준 평균 (None이면 아직 수집 중)
        }
    """
    _no = {"detected": False, "S_high": 0.0, "S_low": 0.0, "direction": "", "mu": None}
    key = f"{device_id}:{metric}"
    save_snapshot = None

    with _lock:
        st = _get_or_init(key)

        # ── 재산출용 롤링 버퍼 업데이트 ──────────────────
        st["tick"] += 1
        rb = st["recent_buf"]
        rb.append(value)
        if len(rb) > BASELINE_POINTS:
            rb.pop(0)

        # ── 기준값 수집 단계 (최초) ───────────────────────
        if st["mu"] is None:
            st["baseline_buf"].append(value)
            if len(st["baseline_buf"]) >= BASELINE_POINTS:
                buf = st["baseline_buf"]
                st["mu"] = mean(buf)
                try:
                    st["sigma"] = stdev(buf)
                except Exception:
                    st["sigma"] = EPS
                st["baseline_buf"] = []
                save_snapshot = {
                    k: {**v, "recent_buf": list(v["recent_buf"]), "baseline_buf": list(v["baseline_buf"])}
                    for k, v in _state.items()
                }
            result = _no

        else:
            # ── baseline 주기 재산출 ──────────────────────
            if st["tick"] % REBASELINE_TICKS == 0 and len(rb) >= BASELINE_POINTS:
                new_mu = mean(rb)
                try:
                    new_sigma = stdev(rb)
                except Exception:
                    new_sigma = EPS
                # 가스 환경이 실제로 변했을 때만 재산출 (3% 이상 변화, 5%→3% 완화)
                # 이유: 4% 변화도 정상 구간 드리프트 유발 가능. 너무 보수적이면 FP 누적.
                # >= 사용: 정확히 3.0% 변화도 재산출 포함 (경계값 포함).
                if abs(new_mu - st["mu"]) / (st["mu"] + EPS) >= 0.03:
                    st["mu"]     = new_mu
                    st["sigma"]  = max(new_sigma, EPS)
                    st["S_high"] = 0.0
                    st["S_low"]  = 0.0
                    save_snapshot = {
                    k: {**v, "recent_buf": list(v["recent_buf"]), "baseline_buf": list(v["baseline_buf"])}
                    for k, v in _state.items()
                }

            # ── CUSUM 업데이트 ────────────────────────────
            mu        = st["mu"]
            raw_sigma = st["sigma"]
            # baseline 전체가 동일값이면 sigma=0 → h=0 → 모든 변화 오탐 방지
            # mu 비율 기반 최솟값 적용 (2% or 0.1 ppm 중 큰 것)
            sigma = raw_sigma if raw_sigma >= EPS else max(abs(mu) * 0.02, 0.1)
            k     = K_SIGMA * sigma
            # 가스별 H_SIGMA 적용 — metric 이 등록된 가스면 전용값, 아니면 기본값
            h_sigma = _GAS_H_SIGMA.get(metric, H_SIGMA)
            h     = h_sigma * sigma

            st["S_high"] = max(0.0, st["S_high"] + (value - mu - k))
            st["S_low"]  = max(0.0, st["S_low"]  + (mu - k - value))

            S_high = st["S_high"]
            S_low  = st["S_low"]

            over_h    = S_high > h or S_low > h
            direction = ""

            # ── 절대값 게이트 ─────────────────────────────────
            # caution_th 가 주어진 경우, 현재값이 안전 구간이면 알람 억제.
            # S 는 리셋하지 않으므로 위험 구간 진입 즉시 탐지 가능.
            in_alarm_zone = True
            if caution_th is not None and over_h:
                if lower_is_worse:
                    # O2: caution×(1+margin) 초과이면 아직 안전
                    in_alarm_zone = value <= caution_th * (1 + _O2_GATE_MARGIN)
                else:
                    # 일반 가스: caution×gate_ratio 미만이면 안전
                    in_alarm_zone = value >= caution_th * _GATE_RATIO

            detected = over_h and in_alarm_zone

            # S 리셋: 실제 알람 발화 시에만 (안전 구간에서 S 보존)
            if detected:
                if S_high > h:
                    direction    = "up"
                    st["S_high"] = 0.0
                elif S_low > h:
                    direction   = "down"
                    st["S_low"] = 0.0

            result = {
                "detected":  detected,
                "S_high":    round(S_high, 4),
                "S_low":     round(S_low, 4),
                "direction": direction,
                "mu":        round(mu, 4),
            }

    if save_snapshot is not None:
        model_store.save_json('cusum_state', save_snapshot)

    return result
