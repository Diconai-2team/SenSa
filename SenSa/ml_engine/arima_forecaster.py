"""
ml_engine/arima_forecaster.py — ARIMA 시계열 예측 (STEP G)

출력 상태: PREDICTIVE_ALERT (위험 예측) / PREDICTIVE_WARNING (주의 예측)

동작:
  - ARIMA(1,1,1) 모델을 슬라이딩 윈도우 데이터로 학습.
  - steps=10 앞을 예측 (약 10 tick 뒤 값).
  - 예측값이 임계치 초과 시 예측 알람 발행.
  - 데이터 부족 / 학습 실패 시 NORMAL 반환 (safe fallback).

성능:
  - (device_id, metric) 별 모델 캐시 유지.
  - RETRAIN_INTERVAL 포인트마다 재학습 (매 틱 fit 방지).
  - 캐시된 모델은 apply(new_data) 로 빠르게 예측값만 갱신.

학습 데이터 정제 (클리핑 방식):
  - danger 초과값을 제거하지 않고 danger 임계치로 클리핑.
  - 이유: 제거(삭제)는 시계열 연속성을 파괴하여 차분(d=1)이 오작동.
          클리핑은 시간 간격을 유지하면서 이상값이 "정상 추세"로
          학습되는 개념 오염을 방지.
  - O2 (lower_is_worse): 양방향 클리핑 지원.
      danger_threshold (하한=16%) 미만  → 16% 로 올림.
      danger_threshold_high (상한=23.5%) 초과 → 23.5% 로 내림.
      → 안전 범위 [16%, 23.5%] 밖의 학습을 모두 차단.
  - 일반 가스: danger 초과값을 danger 수준으로 내려 클리핑.
"""
import threading
import warnings

import numpy as np
from . import model_store

MIN_POINTS = 30         # ARIMA 학습 최소 포인트 수
FORECAST_STEPS = 10     # 예측 앞 단계 수 [운영 전환 시] → 10 유지 (dev 30초 → 운영 10분 예측)
RETRAIN_INTERVAL = 50   # N 포인트마다 재학습 [운영 전환 시] → 25 (dev 2.5분 → 운영 25분, 너무 느리므로)

_lock = threading.Lock()
_cache: dict[str, dict] = {}      # key → {result, trained_at_count}
_training: set[str] = set()       # 현재 비동기 학습 중인 key

# 동시 백그라운드 ARIMA 학습 제한 (CPU 포화 방지)
_train_semaphore = threading.Semaphore(2)

# ── AIPrediction 피드백 기반 조기 재학습 ──────────────────────────────────────
# ARIMA가 연속으로 N회 예측 실패하면 캐시를 즉시 삭제 → 다음 틱에 재학습 시작.
# 재시작 시 카운터 리셋은 의도된 동작 (cold start = 깨끗한 재학습 기회).
EARLY_RETRAIN_THRESHOLD = 3    # 연속 실패 N회 시 강제 재학습
_failure_counts: dict[str, int] = {}   # key → 연속 실패 횟수


def _clip_for_arima(
    values: list[float],
    danger_threshold: float | None,
    lower_is_worse: bool,
    danger_threshold_high: float | None = None,
) -> np.ndarray:
    """
    시계열 연속성을 유지하면서 이상값을 정제.

    제거(삭제) 방식은 시간 인덱스에 갭을 만들어 ARIMA(d=1) 차분을 왜곡.
    클리핑 방식은 시간 순서를 보존하면서 극단값이 "정상 추세"로 학습되는
    개념 오염을 방지.

    lower_is_worse=True (O2):
        danger_threshold(16%) 미만          → 16% 로 올림 (하향 위험 클리핑)
        danger_threshold_high(23.5%) 초과   → 23.5% 로 내림 (상향 위험 클리핑)
        두 값이 모두 주어지면 안전 범위 [16%, 23.5%] 로 양방향 클리핑.

    lower_is_worse=False (일반 가스):
        danger_threshold 초과 → danger 로 내림 (위험하게 높은 값을 안전 상한으로 내림)
        danger_threshold_high 는 무시 (단방향 임계 가스에는 해당 없음).
    """
    arr = np.array(values, dtype=float)
    if danger_threshold is None:
        return arr
    if lower_is_worse:
        # O2 양방향: np.clip(arr, 하한, 상한)
        # danger_threshold_high 가 None 이면 상한 없이 하한만 클리핑
        return np.clip(arr, danger_threshold, danger_threshold_high)
    else:
        return np.clip(arr, None, danger_threshold)


def _fit_arima(
    values: list[float],
    danger_threshold: float | None = None,
    lower_is_worse: bool = False,
    danger_threshold_high: float | None = None,
):
    """
    statsmodels ARIMA(1,1,1) 학습. 실패 시 None 반환.

    danger_threshold / lower_is_worse / danger_threshold_high:
        학습 전 클리핑 적용 (이상값 학습 방지).
        None 이면 클리핑 없이 원본 그대로 사용.
        O2: danger_threshold=16.0, danger_threshold_high=23.5 → 양방향 클리핑.
    """
    try:
        from statsmodels.tsa.arima.model import ARIMA
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arr = _clip_for_arima(values, danger_threshold, lower_is_worse, danger_threshold_high)
            fitted = ARIMA(arr, order=(1, 1, 1)).fit()
            return fitted
    except Exception:
        return None


def _background_fit(
    key: str,
    values: list[float],
    n: int,
    danger_threshold: float | None = None,
    lower_is_worse: bool = False,
    danger_threshold_high: float | None = None,
) -> None:
    """별도 스레드에서 ARIMA 학습 후 캐시에 저장. 세마포어로 동시 2개 제한."""
    with _train_semaphore:
        fitted = _fit_arima(values, danger_threshold, lower_is_worse, danger_threshold_high)
    snapshot = None
    with _lock:
        _training.discard(key)
        if fitted is not None:
            _cache[key] = {"result": fitted, "trained_at_count": n}
            snapshot = dict(_cache)
    if snapshot is not None:
        model_store.save_pickle('arima_cache', snapshot)


def _get_fitted(
    device_id: str,
    metric: str,
    values: list[float],
    danger_threshold: float | None = None,
    lower_is_worse: bool = False,
    danger_threshold_high: float | None = None,
):
    """
    캐시 히트  → 캐시된 모델 반환 (빠름).
    캐시 미스  → 백그라운드 스레드에서 학습 예약 후 즉시 None 반환.
    재학습 시점 → 백그라운드 스레드에서 갱신.

    danger_threshold / lower_is_worse / danger_threshold_high 는 백그라운드 학습에
    전달되어 재학습 시 클리핑이 일관되게 적용됨.
    O2: danger_threshold=16.0, danger_threshold_high=23.5 → 양방향 클리핑.
    """
    key = f"{device_id}:{metric}"
    n = len(values)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            # 첫 학습: 캐시 없음 → 백그라운드에서 학습, 지금은 NORMAL
            if key not in _training:
                _training.add(key)
                threading.Thread(
                    target=_background_fit,
                    args=(key, list(values), n, danger_threshold, lower_is_worse, danger_threshold_high),
                    daemon=True,
                ).start()
            return None
        # 재학습 주기 도달 시 백그라운드에서 갱신 (현재 캐시는 계속 사용)
        if (n - entry["trained_at_count"]) >= RETRAIN_INTERVAL and key not in _training:
            _training.add(key)
            threading.Thread(
                target=_background_fit,
                args=(key, list(values), n, danger_threshold, lower_is_worse, danger_threshold_high),
                daemon=True,
            ).start()
        return entry["result"]


def invalidate_cache(device_id: str, metric: str) -> None:
    """
    특정 (device, metric) 의 ARIMA 캐시를 즉시 삭제.

    다음 `forecast()` 호출 시 백그라운드 재학습이 시작됨.
    이미 학습 중(_training)인 경우: 해당 스레드가 완료되면 덮어쓰이므로 안전.

    호출 위치:
        record_prediction_failure() — 연속 실패 EARLY_RETRAIN_THRESHOLD 도달 시
    """
    key = f"{device_id}:{metric}"
    with _lock:
        _cache.pop(key, None)
        # 진행 중 학습 마크도 제거 → 다음 호출이 새 학습을 즉시 스케줄
        _training.discard(key)


def record_prediction_failure(device_id: str, metric: str) -> None:
    """
    AIPrediction 결과가 failure 일 때 호출.

    연속 실패 횟수를 추적하고, EARLY_RETRAIN_THRESHOLD 도달 시
    캐시를 무효화하여 다음 틱에 재학습을 트리거.

    설계:
        성공 1회면 카운터 리셋 — 일시적 실패는 무시.
        threshold=3 이면 "3회 연속 실패 = 모델이 체계적으로 틀림" 으로 판단.
    """
    key = f"{device_id}:{metric}"
    _failure_counts[key] = _failure_counts.get(key, 0) + 1
    if _failure_counts[key] >= EARLY_RETRAIN_THRESHOLD:
        _failure_counts[key] = 0   # 카운터 리셋 (재학습 트리거 후 다시 쌓기)
        invalidate_cache(device_id, metric)
        import logging
        logging.getLogger(__name__).info(
            "[arima] 연속 실패 %d회 → %s:%s 캐시 무효화, 조기 재학습 예약",
            EARLY_RETRAIN_THRESHOLD, device_id, metric,
        )


def record_prediction_success(device_id: str, metric: str) -> None:
    """
    AIPrediction 결과가 success 일 때 호출 — 연속 실패 카운터 리셋.
    """
    key = f"{device_id}:{metric}"
    _failure_counts.pop(key, None)


def forecast(
    values: list[float],
    caution_threshold: float | None,
    danger_threshold: float | None,
    lower_is_worse: bool = False,
    device_id: str = "",
    metric: str = "",
    danger_threshold_high: float | None = None,
) -> dict:
    """
    미래 값 예측 후 임계치와 비교.

    Args:
        values:                슬라이딩 윈도우 값 목록
        caution_threshold:     주의 임계값 (None이면 비교 생략)
        danger_threshold:      위험 임계값 (None이면 비교 생략)
        lower_is_worse:        O2 처럼 낮을수록 위험한 경우 True
        device_id / metric:    캐시 키 (없으면 캐시 미사용)
        danger_threshold_high: O2 상단 위험 임계치(23.5%) — 양방향 클리핑 상한.
                               일반 가스는 None (단방향 클리핑만 사용).

    Returns:
        {"status": "PREDICTIVE_ALERT" | "PREDICTIVE_WARNING" | "NORMAL",
         "predicted_max": float, "steps": int, "model_ready": bool}
    """
    _no_result = {"status": "NORMAL", "predicted_max": 0.0, "predicted_values": [], "steps": FORECAST_STEPS, "model_ready": False}

    if len(values) < MIN_POINTS:
        return _no_result

    # 캐시 키가 있으면 캐시 사용, 없으면 매번 학습
    # danger_threshold / lower_is_worse / danger_threshold_high 를 함께 전달 → 클리핑 일관 적용
    if device_id and metric:
        fitted = _get_fitted(device_id, metric, values, danger_threshold, lower_is_worse, danger_threshold_high)
    else:
        fitted = _fit_arima(values, danger_threshold, lower_is_worse, danger_threshold_high)

    if fitted is None:
        return _no_result

    try:
        # apply로 최신 데이터 반영 후 예측 (재학습 없이 빠름)
        arr = np.array(values, dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            refreshed = fitted.apply(arr)
            preds = list(refreshed.forecast(steps=FORECAST_STEPS))
    except Exception:
        return _no_result

    representative = min(preds) if lower_is_worse else max(preds)

    status = "NORMAL"
    if danger_threshold is not None:
        exceeds = representative < danger_threshold if lower_is_worse else representative >= danger_threshold
        if exceeds:
            status = "PREDICTIVE_ALERT"
    if status == "NORMAL" and caution_threshold is not None:
        exceeds = representative < caution_threshold if lower_is_worse else representative >= caution_threshold
        if exceeds:
            status = "PREDICTIVE_WARNING"

    return {
        "status": status,
        "predicted_max": round(representative, 4),
        "predicted_values": [round(float(p), 4) for p in preds],
        "steps": FORECAST_STEPS,
        "model_ready": True,
    }
