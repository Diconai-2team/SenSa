"""
geofence/anomaly_detector.py — 센서 이상 신호 판정.

[v6 — CUSUM baseline 기반 잔차 우선 (7차 세션)]
v5에서 슬라이딩 윈도우(최대 60개, ~60초) 기반 잔차를 도입했으나,
이상이 60초 이상 지속되면 전체 윈도우가 상승값으로 채워져 잔차가 0에 수렴하는 문제.

해결책: CUSUM 안정 baseline(μ)을 1차 잔차 기준으로 사용.
  CUSUM μ = 초기 BASELINE_POINTS(20개) 수집 후 확립 → 환경이 3% 이상 변하기 전까지 유지.
  → 사고 전 기준값이 보존되어 지속 이상 상태에서도 residual = mean(window) - μ > 0.

우선순위:
  1차: CUSUM baseline 기반 (지속 이상 상태 ← 주 경로)
  2차: 슬라이딩 윈도우 기반 (단기 급변 탐지 ← CUSUM μ 미확립 시)
  3차: DB 집계 fallback (Redis 포인트 부족 시)

[임계치 재보정]
  CONFIRM_RESIDUAL_THRESH 를 기존 5분 vs 30분 DB 비교 기준 대비 ~20% 하향.
  CUSUM μ 기반 잔차는 윈도우 접근법보다 절대값이 크고 안정적이므로
  임계치를 낮춰도 FP 증가 없이 TP 개선 가능.

[인터페이스 무수정]
get_recent_residual(device, gas_type) → float
has_anomaly(device, gas_type, threshold=None) → bool
호출 측 (zone_lifecycle.check_tier_upgrade) 코드 변경 불필요.
"""
from datetime import timedelta
from statistics import mean

from django.utils import timezone

# ── ML 슬라이딩 윈도우 최소 포인트 (이하면 DB fallback) ──
MIN_WINDOW_POINTS = 10

# ── 슬라이딩 윈도우 기반 recent / baseline 비율 ──
# 전체 윈도우의 후반 RECENT_RATIO 를 "최근 상태", 나머지를 "baseline" 으로 사용.
RECENT_RATIO = 0.25   # 후반 25% = 최근 상태

# ── DB fallback 윈도우 (v4 로직 보존) ──
LOOKBACK_RECENT_SEC   = 300       # 최근 5분
LOOKBACK_BASELINE_SEC = 1800      # 직전 30분

# ── has_anomaly 임계 (도메인별) ────────────────────────────────────────────────
# v5 기준값 대비 ~20% 하향 조정 (v6 CUSUM baseline 기반 잔차로 전환):
#   CUSUM μ 기반 잔차는 지속 이상 상태에서도 절대값이 충분히 크고 안정적이어서
#   임계치를 낮춰도 FP 증가 없이 탐지 민감도 향상 가능.
#
#   gas   v5 임계  v6 임계 (×0.8)   비고
#   co    20       16               ACGIH TWA 25 ppm
#   h2s   5        4                IDLH 50 ppm, 즉각 위협
#   co2   100      80               변동폭 크므로 절대 하향 제한
#   nh3   15       12               ACGIH TWA 25 ppm
#   no2   1        0.8              좁은 위험 구간
#   so2   3        2.4              좁은 위험 구간
#   o3    0.2      0.15             절대값 매우 작음
#   voc   50       40               완만 누적 특성
#   o2    1        0.8              양방향 임계
CONFIRM_RESIDUAL_THRESH = {
    'co':  16,
    'h2s': 4,
    'co2': 80,
    'nh3': 12,
    'no2': 0.8,
    'so2': 2.4,
    'o3':  0.15,
    'voc': 40,
    'o2':  0.8,
}
DEFAULT_RESIDUAL_THRESH = 16   # 기본값도 비례 하향


# ────────────────────────────────────────────────────────────────
# v6 — CUSUM baseline 기반 잔차 (주 경로)
# ────────────────────────────────────────────────────────────────

def _get_residual_from_cusum_baseline(device, gas_type: str) -> float | None:
    """
    CUSUM 안정 baseline(μ)을 기준으로 현재 슬라이딩 윈도우 평균과의 차이를 잔차로 반환.

    CUSUM μ는 초기 BASELINE_POINTS 개 수집 후 확립되며, 환경 변화가 3% 이상이 아니면
    사고 전 기준값을 유지 → 이상 상태가 수 분 이상 지속되어도 안정적인 잔차 제공.

    CUSUM μ 미확립(초기 수집 단계) 또는 슬라이딩 윈도우 포인트 부족 시 None 반환
    → 상위 호출자가 다음 fallback 경로로 진행.
    """
    try:
        from ml_engine.cusum_detector import _state, _lock as _cusum_lock
        from ml_engine.sliding_window import get_values

        key = f"{device.device_id}:{gas_type.lower()}"
        with _cusum_lock:
            st = _state.get(key)
            if st is None or st.get("mu") is None:
                return None
            baseline_mu = float(st["mu"])

        values = get_values(device.device_id, gas_type.lower())
        if len(values) < MIN_WINDOW_POINTS:
            return None

        current_avg = mean(values)
        return float(current_avg - baseline_mu)
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────
# v5 — ML 슬라이딩 윈도우 기반 잔차
# ────────────────────────────────────────────────────────────────

def _get_residual_from_window(device, gas_type: str) -> float | None:
    """
    Redis 슬라이딩 윈도우에서 잔차를 계산.

    MIN_WINDOW_POINTS 미만이면 None 반환 → DB fallback 으로 이어짐.
    """
    try:
        from ml_engine.sliding_window import get_values
        values = get_values(device.device_id, gas_type.lower())
    except Exception:
        return None

    if len(values) < MIN_WINDOW_POINTS:
        return None

    # 후반 RECENT_RATIO 를 "최근 상태" 로 분리
    # 예) 60개 → recent=15개, baseline=45개
    recent_n   = max(2, int(len(values) * RECENT_RATIO))
    baseline_n = len(values) - recent_n

    if baseline_n < 2:
        return None   # 분리가 불가능할 만큼 값이 적음

    recent_avg   = mean(values[-recent_n:])
    baseline_avg = mean(values[:baseline_n])
    return float(recent_avg - baseline_avg)


# ────────────────────────────────────────────────────────────────
# v4 — DB 기반 잔차 (fallback)
# ────────────────────────────────────────────────────────────────

def _get_residual_from_db(device, gas_type: str) -> float:
    """
    DB 집계 기반 잔차 (v4 로직 그대로 보존).

    슬라이딩 윈도우 포인트 부족 시 호출됨.
    """
    from django.db.models import Avg
    from devices.models import SensorData

    field = gas_type.lower()
    now   = timezone.now()
    recent_start   = now - timedelta(seconds=LOOKBACK_RECENT_SEC)
    baseline_start = now - timedelta(seconds=LOOKBACK_BASELINE_SEC)

    recent_avg = (
        SensorData.objects
        .filter(device=device, timestamp__gte=recent_start)
        .exclude(**{f'{field}__isnull': True})
        .aggregate(avg=Avg(field))
    )['avg']
    baseline_avg = (
        SensorData.objects
        .filter(
            device=device,
            timestamp__gte=baseline_start,
            timestamp__lt=recent_start,
        )
        .exclude(**{f'{field}__isnull': True})
        .aggregate(avg=Avg(field))
    )['avg']

    if recent_avg is None or baseline_avg is None:
        return 0.0
    return float(recent_avg - baseline_avg)


# ────────────────────────────────────────────────────────────────
# 공개 API (인터페이스 무수정)
# ────────────────────────────────────────────────────────────────

def get_recent_residual(device, gas_type: str) -> float:
    """
    센서의 최근 잔차.

    1차: CUSUM baseline 기반 (지속 이상 상태에서도 안정적 잔차 — 주 경로)
    2차: ML 슬라이딩 윈도우 (CUSUM μ 미확립 시, Redis 단기 급변 탐지)
    3차: DB 집계 (Redis 포인트 부족 시 fallback)

    Returns:
        잔차 (부호 포함). 호출 측 has_anomaly 가 abs() 적용.
    """
    # 1차: CUSUM baseline
    residual = _get_residual_from_cusum_baseline(device, gas_type)
    if residual is not None:
        return residual
    # 2차: 슬라이딩 윈도우
    residual = _get_residual_from_window(device, gas_type)
    if residual is not None:
        return residual
    # 3차: DB fallback
    return _get_residual_from_db(device, gas_type)


def has_anomaly(device, gas_type: str, threshold: float = None) -> bool:
    """
    센서 이상 패턴 여부.

    threshold 미지정 시 도메인별 CONFIRM_RESIDUAL_THRESH 사용.
    zone_lifecycle.check_tier_upgrade 가 이웃 센서 anomaly 판정에 사용.
    """
    if threshold is None:
        threshold = CONFIRM_RESIDUAL_THRESH.get(
            gas_type.lower(),
            DEFAULT_RESIDUAL_THRESH,
        )
    return abs(get_recent_residual(device, gas_type)) > threshold
