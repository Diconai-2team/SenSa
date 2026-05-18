"""
ml_engine/isolation_forest.py — Isolation Forest 이상 탐지 (STEP F)

출력 상태: ML_ANOMALY

특징 벡터 (5차원):
  value      — 현재 측정값
  roll_mean  — 정상 범위 슬라이딩 윈도우 평균 (임계치 초과값 제외)
  roll_std   — 정상 범위 슬라이딩 윈도우 표준편차
  diff       — 현재값 - 직전 실측값 (이상값 포함, 변화율 보존)
  ratio      — 현재값 / (정상 baseline roll_mean + EPS)

설계:
  - 모델은 (device_id, metric) 조합별로 in-process dict에 캐시.
  - 데이터가 MIN_TRAIN 포인트 이상 쌓이면 학습 시작.
  - RETRAIN_INTERVAL 포인트마다 재학습 (개념 표류 대응).
  - contamination=0.03 (실측 데이터 기반: 임계치 알람/전체 ≈ 2.6%)

학습 데이터 정제 (준지도 방식):
  - danger 임계치 이상인 값을 학습 윈도우에서 제거.
  - 모델이 "이상값도 정상"이라고 학습하는 개념 오염 방지.
  - 정제 후 MIN_TRAIN 미만이면 전체 윈도우로 fallback.
"""
import threading
from statistics import mean, stdev
from sklearn.ensemble import IsolationForest
import numpy as np
from . import model_store

EPS = 1e-9
MIN_TRAIN = 30          # 학습 최소 샘플 수
CONTAMINATION = 0.03    # 이상 비율 — 실측 데이터 기반 (임계치 알람/전체 2.6%)
RETRAIN_INTERVAL = 50   # N 포인트마다 재학습

_lock = threading.Lock()
_models: dict[str, dict] = {}   # key → {model, trained_at_count}

# GAS_THRESHOLDS + O2 상수 lazy import (순환 import 방지, 단일 출처 유지)
_GAS_THRESHOLDS = None
_O2_DANGER_LOW  = None  # lazy init
_O2_DANGER_HIGH = None  # lazy init


def _get_thresholds():
    global _GAS_THRESHOLDS, _O2_DANGER_LOW, _O2_DANGER_HIGH
    if _GAS_THRESHOLDS is None:
        from alerts.services import GAS_THRESHOLDS, O2_DANGER_LOW, O2_DANGER_HIGH
        _GAS_THRESHOLDS = GAS_THRESHOLDS
        _O2_DANGER_LOW  = O2_DANGER_LOW
        _O2_DANGER_HIGH = O2_DANGER_HIGH
    return _GAS_THRESHOLDS


def _filter_normal_values(metric: str, values: list[float]) -> list[float]:
    """
    danger 임계치 이상인 값을 제거하여 정상 baseline 만 반환.
    임계치 정보가 없는 메트릭(전력 등)은 전체 반환.
    """
    thresholds = _get_thresholds()  # O2 상수도 여기서 로드됨
    if metric == 'o2':
        return [v for v in values if _O2_DANGER_LOW <= v <= _O2_DANGER_HIGH]

    t = thresholds.get(metric)
    if not t:
        return values

    danger = t['danger']
    return [v for v in values if v < danger]


def _make_features(baseline: list[float], current: float, last_actual: float | None = None) -> np.ndarray:
    """
    단일 관측값에 대한 5차원 특징 벡터 생성.

    baseline — 정제된 정상값 목록 (mu/sigma 계산 기준)
    last_actual — 직전 실측값 (diff 계산용; None 이면 baseline[-1] 사용)
    """
    mu = mean(baseline) if baseline else current
    try:
        sigma = stdev(baseline) if len(baseline) >= 2 else 0.0
    except Exception:
        sigma = 0.0
    prev = last_actual if last_actual is not None else (baseline[-1] if baseline else current)
    diff = current - prev
    ratio = current / (mu + EPS)
    return np.array([[current, mu, sigma, diff, ratio]], dtype=float)


def _make_feature_matrix(values: list[float]) -> np.ndarray:
    """전체 윈도우에 대한 특징 행렬 생성 (학습용)."""
    rows = []
    mu = mean(values)
    try:
        sigma = stdev(values)
    except Exception:
        sigma = 0.0
    for i, v in enumerate(values):
        diff = v - values[i - 1] if i > 0 else 0.0
        ratio = v / (mu + EPS)
        rows.append([v, mu, sigma, diff, ratio])
    return np.array(rows, dtype=float)


def detect_ml_anomaly(device_id: str, metric: str, values: list[float], current: float) -> dict:
    """
    Isolation Forest 이상 탐지.

    Returns:
        {"detected": bool, "score": float, "model_ready": bool}
    """
    if len(values) < MIN_TRAIN:
        return {"detected": False, "score": 0.0, "model_ready": False}

    # 학습 데이터 정제: danger 초과값 제거 → MIN_TRAIN 미만이면 전체 fallback
    clean = _filter_normal_values(metric, values)
    train_values = clean if len(clean) >= MIN_TRAIN else values

    model_key = f"{device_id}:{metric}"
    with _lock:
        entry = _models.get(model_key)
        n = len(values)
        should_train = (
            entry is None
            or (n - entry.get("trained_at_count", 0)) >= RETRAIN_INTERVAL
        )
        if should_train:
            X = _make_feature_matrix(train_values)
            model = IsolationForest(
                n_estimators=100,
                contamination=CONTAMINATION,
                random_state=42,
            )
            model.fit(X)
            _models[model_key] = {"model": model, "trained_at_count": n}
            entry = _models[model_key]
            snapshot = dict(_models)
        else:
            snapshot = None

        model = entry["model"]

    if snapshot is not None:
        model_store.save_pickle('if_models', snapshot)

    # 탐지: baseline(정제값)으로 mu/sigma, 실제 직전 측정값으로 diff
    # values[-1] == current (push 후 조회이므로), 진짜 이전값은 [-2]
    last_prev = values[-2] if len(values) >= 2 else current
    x = _make_features(train_values, current, last_actual=last_prev)
    prediction = model.predict(x)[0]   # 1=정상, -1=이상
    score = float(model.score_samples(x)[0])

    return {
        "detected": prediction == -1,
        "score": round(score, 4),
        "model_ready": True,
    }
