"""
ml_engine/arima_forecaster.py — ARIMA 시계열 예측 (STEP G)

출력 상태: PREDICTIVE_ALERT (위험 예측) / PREDICTIVE_WARNING (주의 예측)

동작:
  - ARIMA(1,1,1) 모델을 슬라이딩 윈도우 데이터로 학습.
  - steps=3 앞을 예측 (약 3 tick 뒤 값).
  - 예측값이 임계치 초과 시 예측 알람 발행.
  - 데이터 부족 / 학습 실패 시 NORMAL 반환 (safe fallback).

성능:
  - (device_id, metric) 별 모델 캐시 유지.
  - RETRAIN_INTERVAL 포인트마다 재학습 (매 틱 fit 방지).
  - 캐시된 모델은 apply(new_data) 로 빠르게 예측값만 갱신.
"""
import threading
import warnings

import numpy as np
from . import model_store

MIN_POINTS = 30         # ARIMA 학습 최소 포인트 수
FORECAST_STEPS = 10     # 예측 앞 단계 수 (3→10: 리드 타임 약 10초로 확보)
RETRAIN_INTERVAL = 50   # N 포인트마다 재학습

_lock = threading.Lock()
_cache: dict[str, dict] = {}      # key → {result, trained_at_count}
_training: set[str] = set()       # 현재 비동기 학습 중인 key

# 동시 백그라운드 ARIMA 학습 제한 (CPU 포화 방지)
_train_semaphore = threading.Semaphore(2)


def _fit_arima(values: list[float]):
    """statsmodels ARIMA(1,1,1) 학습. 실패 시 None 반환."""
    try:
        from statsmodels.tsa.arima.model import ARIMA
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arr = np.array(values, dtype=float)
            fitted = ARIMA(arr, order=(1, 1, 1)).fit()
            return fitted
    except Exception:
        return None


def _background_fit(key: str, values: list[float], n: int) -> None:
    """별도 스레드에서 ARIMA 학습 후 캐시에 저장. 세마포어로 동시 2개 제한."""
    with _train_semaphore:
        fitted = _fit_arima(values)
    snapshot = None
    with _lock:
        _training.discard(key)
        if fitted is not None:
            _cache[key] = {"result": fitted, "trained_at_count": n}
            snapshot = dict(_cache)
    if snapshot is not None:
        model_store.save_pickle('arima_cache', snapshot)


def _get_fitted(device_id: str, metric: str, values: list[float]):
    """
    캐시 히트  → 캐시된 모델 반환 (빠름).
    캐시 미스  → 백그라운드 스레드에서 학습 예약 후 즉시 None 반환.
    재학습 시점 → 백그라운드 스레드에서 갱신.
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
                    args=(key, list(values), n),
                    daemon=True,
                ).start()
            return None
        # 재학습 주기 도달 시 백그라운드에서 갱신 (현재 캐시는 계속 사용)
        if (n - entry["trained_at_count"]) >= RETRAIN_INTERVAL and key not in _training:
            _training.add(key)
            threading.Thread(
                target=_background_fit,
                args=(key, list(values), n),
                daemon=True,
            ).start()
        return entry["result"]


def forecast(
    values: list[float],
    caution_threshold: float | None,
    danger_threshold: float | None,
    lower_is_worse: bool = False,
    device_id: str = "",
    metric: str = "",
) -> dict:
    """
    미래 값 예측 후 임계치와 비교.

    Args:
        values:             슬라이딩 윈도우 값 목록
        caution_threshold:  주의 임계값 (None이면 비교 생략)
        danger_threshold:   위험 임계값 (None이면 비교 생략)
        lower_is_worse:     O2 처럼 낮을수록 위험한 경우 True
        device_id / metric: 캐시 키 (없으면 캐시 미사용)

    Returns:
        {"status": "PREDICTIVE_ALERT" | "PREDICTIVE_WARNING" | "NORMAL",
         "predicted_max": float, "steps": int, "model_ready": bool}
    """
    _no_result = {"status": "NORMAL", "predicted_max": 0.0, "predicted_values": [], "steps": FORECAST_STEPS, "model_ready": False}

    if len(values) < MIN_POINTS:
        return _no_result

    # 캐시 키가 있으면 캐시 사용, 없으면 매번 학습
    if device_id and metric:
        fitted = _get_fitted(device_id, metric, values)
    else:
        fitted = _fit_arima(values)

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
