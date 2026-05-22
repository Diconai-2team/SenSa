"""
ml_engine/detectors.py — 통계 기반 이상 탐지

STEP D — Robust Z-score 이상 탐지  → ANOMALY_WARNING
STEP E — Change Point 급변 탐지    → TREND_SHIFT

두 검출기 모두 슬라이딩 윈도우 값 목록(list[float])을 입력으로 받음.
결과: 감지 시 True, 미감지 시 False + score 반환.

[Robust Z-score 전환 이유]
  기존 mean/stdev 기반 z-score는 이상값이 윈도우에 섞이면
  mean이 위로 끌려 z-score가 줄어들어 Recall이 저하됨.
  median/MAD(Median Absolute Deviation)는 이상값에 강건(robust)하여
  정상 baseline이 오염돼도 이상값을 일관되게 탐지.
  MAD → σ 환산: σ_est = 1.4826 × MAD (정규분포 가정 하 NIST 표준)
"""
import math
from statistics import mean, median, stdev

EPS = 1e-9
ZSCORE_THRESHOLD = 3.0      # |z| > 3 → 이상
MEAN_SHIFT_THRESHOLD = 2.5  # mean_shift_score > 2.5 → 급변 (2.0→2.5: FP 감소, 2.0~2.5 범위는 Z-score/CUSUM이 커버)
STD_RATIO_THRESHOLD  = 2.5  # std_ratio > 2.5 → 분산 급변
WINDOW_HALF = 20            # change point 비교 절반 크기 (최소 필요 len = WINDOW_HALF * 2)

# MAD → σ 환산 계수 (정규분포 가정)
_MAD_SCALE = 1.4826


# ───────────────────────────────────────────────
# STEP D — Robust Z-score 이상 탐지
# ───────────────────────────────────────────────

def detect_zscore(values: list[float], current: float) -> dict:
    """
    Robust Z-score (median/MAD 기반) 이상 탐지.

    이상값이 윈도우에 섞여도 median/MAD는 끌려가지 않으므로
    기존 mean/stdev 대비 Recall 개선 효과.

    Returns:
        {"detected": bool, "z_score": float, "mean": float, "std": float}
    """
    if len(values) < 10:
        return {"detected": False, "z_score": 0.0, "mean": current, "std": 0.0}

    med = median(values)
    mad = median([abs(v - med) for v in values])
    sigma = _MAD_SCALE * mad
    # MAD=0 (완전 동일값 또는 이산 분포): stdev로 fallback
    if sigma < EPS:
        try:
            sigma = stdev(values)
        except Exception:
            sigma = 0.0

    if sigma < EPS:
        # MAD=0이고 stdev=0 → 윈도우 전체가 동일값, 분산 정보 없음
        # z-score 탐지 불가 → 다른 탐지기(CUSUM·IsolationForest)에 위임
        return {"detected": False, "z_score": 0.0, "mean": round(med, 4), "std": 0.0}

    z = abs(current - med) / sigma
    return {
        "detected": z > ZSCORE_THRESHOLD,
        "z_score": round(z, 3),
        "mean": round(med, 4),   # 필드명 유지 (API 호환)
        "std": round(sigma, 4),
    }


# ───────────────────────────────────────────────
# STEP E — Change Point 급변 탐지
# ───────────────────────────────────────────────

def detect_changepoint(values: list[float]) -> dict:
    """
    두 구간 비교로 평균·분산 급변 탐지.

    이전 WINDOW_HALF 개 vs 최근 WINDOW_HALF 개 비교.
    mean_shift_score = |mean_curr - mean_prev| / (std_combined + EPS)
    std_ratio        = max(std_curr, std_prev) / (min(std_curr, std_prev) + EPS)

    Returns:
        {"detected": bool, "mean_shift_score": float, "std_ratio": float, "reason": str}
    """
    n = len(values)
    if n < WINDOW_HALF * 2:
        return {"detected": False, "mean_shift_score": 0.0, "std_ratio": 1.0, "reason": "insufficient_data"}

    prev = values[-(WINDOW_HALF * 2):-WINDOW_HALF]
    curr = values[-WINDOW_HALF:]

    mean_prev = mean(prev)
    mean_curr = mean(curr)

    try:
        std_prev = stdev(prev)
    except Exception:
        std_prev = 0.0
    try:
        std_curr = stdev(curr)
    except Exception:
        std_curr = 0.0

    std_combined = math.sqrt((std_prev ** 2 + std_curr ** 2) / 2)
    mean_shift = abs(mean_curr - mean_prev) / (std_combined + EPS)

    std_max = max(std_curr, std_prev)
    std_min = min(std_curr, std_prev)
    std_ratio = std_max / (std_min + EPS)

    detected = mean_shift > MEAN_SHIFT_THRESHOLD or std_ratio > STD_RATIO_THRESHOLD
    reason = ""
    if mean_shift > MEAN_SHIFT_THRESHOLD:
        reason = "mean_shift"
    elif std_ratio > STD_RATIO_THRESHOLD:
        reason = "std_ratio"

    return {
        "detected": detected,
        "mean_shift_score": round(mean_shift, 3),
        "std_ratio": round(std_ratio, 3),
        "reason": reason,
    }
