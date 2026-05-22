"""
ml_engine/pipeline.py — AI 이상 탐지 파이프라인 진입점

우선순위 (높음 → 낮음):
  현재 상태: ML_ANOMALY > ANOMALY_WARNING > TREND_SHIFT > DRIFT_ALERT > NORMAL
  예측 상태: PREDICTIVE_ALERT > PREDICTIVE_WARNING > NORMAL

공개 API:
  analyze(device_id, metric, value, sensor_type='gas') -> dict
    → {
        "current_status": str,        # 현재 이상 탐지 결과
        "predictive_status": str,     # 예측 기반 결과
        "details": {                  # 각 검출기 원시 결과
          "zscore": {...},
          "changepoint": {...},
          "isolation_forest": {...},
          "arima": {...},
          "cusum": {...},
        },
        "window_size": int,
      }

임계치 매핑: alerts.services.GAS_THRESHOLDS 재사용 (O2 포함).
"""
from .sliding_window import push, get_values
from .detectors import detect_zscore, detect_changepoint
from .isolation_forest import detect_ml_anomaly
from .arima_forecaster import forecast
from .cusum_detector import detect_drift

# ─── 가스 임계치 재사용 (alerts.services 와 단일 출처 유지) ───
# 순환 import 방지를 위해 여기서 직접 정의하지 않고 lazy import.
# O2 상수도 동일 함수에서 함께 로드 — 단일 출처 원칙 유지.
_GAS_THRESHOLDS = None
_O2_DANGER_LOW  = None  # lazy init
_O2_CAUTION_LOW = None  # lazy init
_O2_DANGER_HIGH = None  # lazy init — O2 양방향 클리핑 상한

# ── IF 단독 발화 강도 임계 ────────────────────────────────────────────────────
# Isolation Forest score_samples(): 더 음수일수록 이상 (정상 ≈ 0.0 ~ +0.1)
#   ≤ IF_STRONG_SCORE(-0.3): 강한 이상 신호 → 단독 발화도 ML_ANOMALY
#   > IF_STRONG_SCORE       : 경계선 이상    → ANOMALY_WARNING 으로 하향 (FP 억제)
# 설계 근거: score=-0.01(경계)과 score=-0.8(강한) 을 같은 레벨로 처리하면
#   정상에 가까운 경계 샘플이 ML_ANOMALY를 양산 → 오탐 증가.
IF_STRONG_SCORE = -0.3


def _get_gas_thresholds():
    global _GAS_THRESHOLDS, _O2_DANGER_LOW, _O2_CAUTION_LOW, _O2_DANGER_HIGH
    if _GAS_THRESHOLDS is None:
        from alerts.services.classifiers import (
            GAS_THRESHOLDS, O2_DANGER_LOW, O2_CAUTION_LOW, O2_DANGER_HIGH,
        )
        _GAS_THRESHOLDS = GAS_THRESHOLDS
        _O2_DANGER_LOW  = O2_DANGER_LOW
        _O2_CAUTION_LOW = O2_CAUTION_LOW
        _O2_DANGER_HIGH = O2_DANGER_HIGH
    return _GAS_THRESHOLDS


def _get_thresholds_for(metric: str):
    """
    Returns (caution, danger, lower_is_worse, danger_high).
    가스 임계치를 기준으로 반환.

    danger_high: O2 상단 위험 임계치(23.5%) — ARIMA 양방향 클리핑 용.
                 O2 이외 가스는 None.
    """
    thresholds = _get_gas_thresholds()  # O2 상수도 여기서 로드됨
    if metric == 'o2':
        return _O2_CAUTION_LOW, _O2_DANGER_LOW, True, _O2_DANGER_HIGH

    t = thresholds.get(metric)
    if t:
        return t['caution'], t['danger'], False, None
    return None, None, False, None


def analyze(device_id: str, metric: str, value: float, sensor_type: str = 'gas') -> dict:
    """
    단일 측정값 하나에 대해 전체 AI 파이프라인 실행.

    1. 슬라이딩 윈도우에 값 추가
    2. Z-score 이상 탐지      → ANOMALY_WARNING
    3. Change Point 탐지      → TREND_SHIFT
    4. Isolation Forest 탐지  → ML_ANOMALY
    5. ARIMA 예측             → PREDICTIVE_ALERT / PREDICTIVE_WARNING
    6. CUSUM 드리프트 탐지    → DRIFT_ALERT
    """
    # 1. 슬라이딩 윈도우 업데이트
    push(device_id, metric, value)
    values = get_values(device_id, metric)
    w_size = len(values)

    # 2. Z-score
    zscore_result = detect_zscore(values, value)

    # 3. Change Point
    cp_result = detect_changepoint(values)

    # 4. Isolation Forest
    if_result = detect_ml_anomaly(device_id, metric, values, value)

    # 5. ARIMA 예측
    caution_th, danger_th, lower_is_worse, danger_th_high = _get_thresholds_for(metric)
    arima_result = forecast(values, caution_th, danger_th, lower_is_worse,
                            device_id=device_id, metric=metric,
                            danger_threshold_high=danger_th_high)

    # 6. CUSUM 드리프트 — 완만한 농도 상승/하강 감지
    # caution_th 를 함께 전달 → 안전 구간에서 알람 억제 (FP 감소)
    cusum_result = detect_drift(device_id, metric, value,
                                caution_th=caution_th,
                                lower_is_worse=lower_is_worse)

    # ─── 앙상블 투표: 동시 발화 탐지기 집계 ───
    # ARIMA 는 예측(미래) 기반이므로 현재 상태 투표에서 제외.
    fired = []
    if if_result["detected"]:      fired.append("isolation_forest")
    if zscore_result["detected"]:  fired.append("zscore")
    if cp_result["detected"]:      fired.append("changepoint")
    if cusum_result["detected"]:   fired.append("cusum")

    detector_count = len(fired)

    # ─── 현재 상태 결정 ───
    # 우선순위: ML_ANOMALY > ANOMALY_WARNING > TREND_SHIFT > DRIFT_ALERT > NORMAL
    #
    # 2개 이상 탐지기 동시 발화 → ML_ANOMALY 로 에스컬레이션
    # (약한 신호 여럿이 동시에 반응 = 실제 이상일 가능성이 훨씬 높음)
    #
    # IF 단독 발화 정책 (IF_STRONG_SCORE 기반):
    #   score ≤ -0.3 → 강한 이상 신호  → ML_ANOMALY (기존 동작 유지)
    #   score > -0.3 → 경계선 이상 신호 → ANOMALY_WARNING 으로 하향 (FP 억제)
    #
    # CUSUM 단독 발화 → DRIFT_ALERT:
    #   per-gas H_SIGMA + caution_th 게이트 + 재산출 주기 단축으로 FP 충분히 억제.
    #   views.py 에서 device 단위 300s 쿨다운(_device_drift_ts) 으로 틱당 1건 제한.
    #   에스컬레이션(_NO_ESCALATION_TYPES)에서 제외 → danger 승격 없음.
    if detector_count >= 2:
        current_status = "ML_ANOMALY"
    elif if_result["detected"]:
        if if_result.get("score", -1.0) <= IF_STRONG_SCORE:
            current_status = "ML_ANOMALY"
        else:
            # 경계선 단독 발화 — Z-score 수준으로 하향하여 오탐 억제
            current_status = "ANOMALY_WARNING"
    elif zscore_result["detected"]:
        current_status = "ANOMALY_WARNING"
    elif cp_result["detected"]:
        current_status = "TREND_SHIFT"
    elif cusum_result["detected"]:
        current_status = "DRIFT_ALERT"
    else:
        current_status = "NORMAL"

    return {
        "current_status":   current_status,
        "predictive_status": arima_result["status"],
        "detector_count":   detector_count,
        "fired_detectors":  fired,
        "details": {
            "zscore":           zscore_result,
            "changepoint":      cp_result,
            "isolation_forest": if_result,
            "arima":            arima_result,
            "cusum":            cusum_result,
        },
        "window_size":     w_size,
        "current_value":   value,   # 위험 임박 우선 통과 판단용
    }
