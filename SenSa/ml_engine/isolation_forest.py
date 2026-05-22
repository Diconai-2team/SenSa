"""
ml_engine/isolation_forest.py — Isolation Forest 이상 탐지 (STEP F)

출력 상태: ML_ANOMALY

특징 벡터 (6차원, MODEL_VERSION=2):
  value      — 현재 측정값
  roll_mean  — 정상 범위 슬라이딩 윈도우 평균 (임계치 초과값 제외)
  roll_std   — 정상 범위 슬라이딩 윈도우 표준편차
  diff       — 현재값 - 직전 실측값 (이상값 포함, 변화율 보존)
  ratio      — 현재값 / (정상 baseline roll_mean + EPS)
  slope      — 최근 SLOPE_WINDOW 틱의 선형 기울기 (추세 방향 포착)
               꾸준한 상승(+) / 하강(-) 패턴을 단일 틱 diff로는 잡지 못하는 경우 보완.

설계:
  - 모델은 (device_id, metric) 조합별로 in-process dict에 캐시.
  - 데이터가 MIN_TRAIN 포인트 이상 쌓이면 학습 시작.
  - 재학습 주기는 call_count (독립 호출 카운터) 기반.
    슬라이딩 윈도우 크기(n)가 WINDOW_SIZE(60)로 고정되면
    "n - trained_at_count" 차이가 RETRAIN_INTERVAL(50)에 영영 도달하지 못하는 버그 방지.
  - 학습은 백그라운드 스레드에서 실행 — 기존 모델로 탐지 공백 없이 계속.
    동시 학습 세마포어(2개) 로 CPU 포화 방지.
  - contamination=0.03 (실측 데이터 기반: 임계치 알람/전체 ≈ 2.6%)

학습 데이터 정제 (준지도 방식):
  - danger 임계치 이상인 값을 학습 윈도우에서 제거.
  - 모델이 "이상값도 정상"이라고 학습하는 개념 오염 방지.
  - 정제 후 MIN_TRAIN 미만이면 전체 윈도우로 fallback.

모델 버전 관리 (MODEL_VERSION):
  - 특징 차원이 바뀔 때마다 MODEL_VERSION 을 증가.
  - apps.py 로드 시 또는 탐지 시 버전 불일치 항목을 자동 폐기 → 재학습.
  - 버전 불일치 모델로 predict() 를 호출하면 차원 오류(ValueError) 가 발생하므로
    반드시 버전 체크 후 폐기해야 함.
"""
import threading
from statistics import mean, stdev
from sklearn.ensemble import IsolationForest
import numpy as np
from . import model_store

EPS = 1e-9
MIN_TRAIN = 30          # 학습 최소 샘플 수
CONTAMINATION = 0.03    # 이상 비율 기본값 — 실측 데이터 기반 (임계치 알람/전체 ≈ 2.6%)
RETRAIN_INTERVAL = 50   # 호출 N회마다 재학습 (call_count 기반 — 윈도우 크기와 독립)
SLOPE_WINDOW = 10       # slope 계산에 사용할 최근 틱 수

# 특징 차원이 바뀔 때마다 증가 → 구 버전 모델 자동 폐기 (차원 불일치 예외 방지)
MODEL_VERSION = 2

# ── 런타임 동적 contamination ──────────────────────────────────────────────────
# evaluator 의 fp_rate 힌트에 따라 5분마다 ±0.005 씩 자동 조정.
# 범위: [CONTAMINATION_MIN, CONTAMINATION_MAX]
# 기본값은 CONTAMINATION(=0.03) 에서 시작.
CONTAMINATION_MIN = 0.005
CONTAMINATION_MAX = 0.10
_CONTAMINATION_STEP = 0.005   # 1회 조정 단위

_contamination_lock    = threading.Lock()
_dynamic_contamination = CONTAMINATION   # 현재 적용 중인 contamination


def get_contamination() -> float:
    """현재 적용 중인 contamination 값 반환 (thread-safe)."""
    with _contamination_lock:
        return _dynamic_contamination


def set_contamination(new_value: float) -> None:
    """
    contamination 을 새 값으로 변경 (thread-safe).

    범위 [CONTAMINATION_MIN, CONTAMINATION_MAX] 로 클램핑.
    변경 후 다음 재학습 주기(RETRAIN_INTERVAL)에 자동 반영.
    즉시 강제 재학습은 하지 않음 — 50틱 이내 자연 교체로 충분.
    """
    global _dynamic_contamination
    clamped = max(CONTAMINATION_MIN, min(CONTAMINATION_MAX, new_value))
    with _contamination_lock:
        _dynamic_contamination = clamped


_lock = threading.Lock()
_models: dict[str, dict] = {}     # key → {model, trained_call_count, version}

# ── 독립 호출 카운터 (재학습 주기 판단용) ──────────────────────────────────────
# 슬라이딩 윈도우 크기(n)는 WINDOW_SIZE(60)에서 고정되므로
# "n - trained_at_count" 차이가 RETRAIN_INTERVAL(50)을 초과하지 못하는 버그 방지.
# call_count 는 단조 증가(monotonic) → 재학습 조건이 반드시 도달.
_call_counters: dict[str, int] = {}   # key → 누적 호출 횟수

# ── 비동기 학습 상태 ──────────────────────────────────────────────────────────
# ARIMA 와 동일한 패턴:
#   - 학습은 백그라운드 스레드에서 실행 (fit() 소요 시간이 응답 지연 없음)
#   - 학습 중에도 기존 모델로 탐지 계속 → 탐지 공백 없음
#   - 동시 학습 세마포어로 CPU thundering herd 방지
_training: set[str] = set()              # 현재 비동기 학습 중인 key
_train_semaphore = threading.Semaphore(2)  # 동시 백그라운드 학습 최대 2개

# GAS_THRESHOLDS + O2 상수 lazy import (순환 import 방지, 단일 출처 유지)
_GAS_THRESHOLDS = None
_O2_DANGER_LOW  = None  # lazy init
_O2_DANGER_HIGH = None  # lazy init


def _get_thresholds():
    global _GAS_THRESHOLDS, _O2_DANGER_LOW, _O2_DANGER_HIGH
    if _GAS_THRESHOLDS is None:
        from alerts.services.classifiers import GAS_THRESHOLDS, O2_DANGER_LOW, O2_DANGER_HIGH
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


def _calc_slope(values: list[float]) -> float:
    """
    최근 SLOPE_WINDOW 개 값에 대한 선형 회귀 기울기 반환.

    사용 이유:
      diff(1차 차분)는 직전 1틱과의 변화만 포착.
      slope는 최근 N틱의 추세 방향을 포착 — 꾸준한 상승/하강 패턴에 민감.
      예) CO: 20→21→22→23→24 ppm (slope=+1, diff=+1 동일하지만 추세 의미 다름)
          CO: 22→21→24→20→24 ppm (slope≈0, diff=+4 — 요동치는 패턴)

    포인트 부족(< 2) 시 0.0 반환 (safe fallback).
    """
    pts = values[-SLOPE_WINDOW:]
    if len(pts) < 2:
        return 0.0
    try:
        x = np.arange(len(pts), dtype=float)
        slope = float(np.polyfit(x, pts, 1)[0])
        return slope
    except Exception:
        return 0.0


def _make_features(
    baseline: list[float],
    current: float,
    last_actual: float | None = None,
    raw_values: list[float] | None = None,
) -> np.ndarray:
    """
    단일 관측값에 대한 6차원 특징 벡터 생성 (MODEL_VERSION=2).

    baseline   — 정제된 정상값 목록 (mu/sigma 계산 기준)
    last_actual — 직전 실측값 (diff 계산용; None 이면 baseline[-1] 사용)
    raw_values  — 원본(정제 전) 슬라이딩 윈도우 (slope 계산 기준).
                  None 이면 baseline 으로 대체 (slope 정밀도 다소 낮아짐).
    """
    mu = mean(baseline) if baseline else current
    try:
        sigma = stdev(baseline) if len(baseline) >= 2 else 0.0
    except Exception:
        sigma = 0.0
    prev  = last_actual if last_actual is not None else (baseline[-1] if baseline else current)
    diff  = current - prev
    ratio = current / (mu + EPS)
    slope = _calc_slope(raw_values if raw_values is not None else baseline)
    return np.array([[current, mu, sigma, diff, ratio, slope]], dtype=float)


def _make_feature_matrix(values: list[float]) -> np.ndarray:
    """전체 윈도우에 대한 특징 행렬 생성 (학습용, 6차원)."""
    rows = []
    mu = mean(values)
    try:
        sigma = stdev(values)
    except Exception:
        sigma = 0.0
    for i, v in enumerate(values):
        diff  = v - values[i - 1] if i > 0 else 0.0
        ratio = v / (mu + EPS)
        # slope: 현재 포인트 기준 최근 SLOPE_WINDOW 개 슬라이스
        window_slice = values[max(0, i - SLOPE_WINDOW + 1): i + 1]
        slope = _calc_slope(list(window_slice))
        rows.append([v, mu, sigma, diff, ratio, slope])
    return np.array(rows, dtype=float)


def _background_fit(
    model_key: str,
    train_values: list[float],
    call_count_at_trigger: int,
    contamination: float,
) -> None:
    """
    백그라운드 스레드에서 IsolationForest 학습 후 모델 캐시 갱신.

    세마포어로 동시 학습 최대 2개 제한 (CPU thundering herd 방지).
    학습 완료 후 model_store 에 비동기 저장 (락 밖에서 호출).
    """
    with _train_semaphore:
        X = _make_feature_matrix(list(train_values))
        fitted = IsolationForest(
            n_estimators=100,
            contamination=contamination,
            random_state=42,
        )
        fitted.fit(X)

    snapshot = None
    with _lock:
        _training.discard(model_key)
        _models[model_key] = {
            "model":               fitted,
            "trained_call_count":  call_count_at_trigger,
            "version":             MODEL_VERSION,
        }
        snapshot = dict(_models)   # shallow copy

    if snapshot is not None:
        model_store.save_pickle('if_models', snapshot)


def detect_ml_anomaly(device_id: str, metric: str, values: list[float], current: float) -> dict:
    """
    Isolation Forest 이상 탐지.

    [재학습 주기]
      슬라이딩 윈도우 크기(n)는 WINDOW_SIZE(60)로 고정되므로
      n 기반 조건 "n - trained_at_count >= 50" 은 60-30=30 < 50 이라 영구 미달성.
      → call_count (독립 호출 카운터) 기반으로 변경:
         call_count - trained_call_count >= RETRAIN_INTERVAL(50) → 재학습

    [비동기 학습]
      fit() 는 백그라운드 스레드에서 실행 (응답 시간 영향 없음).
      학습 중에도 기존 모델로 탐지 계속 → 탐지 공백 없음.
      최초 학습 완료 전(call_count < MIN_TRAIN)은 model_ready=False 반환.

    Returns:
        {"detected": bool, "score": float, "model_ready": bool}
    """
    if len(values) < MIN_TRAIN:
        return {"detected": False, "score": 0.0, "slope": 0.0, "model_ready": False}

    # 학습 데이터 정제: danger 초과값 제거 → MIN_TRAIN 미만이면 전체 fallback
    clean = _filter_normal_values(metric, values)
    train_values = clean if len(clean) >= MIN_TRAIN else values

    model_key = f"{device_id}:{metric}"

    # ── 1단계: call_count 증가 + 재학습 여부 판단 (락 내, 빠른 연산만) ──────
    with _lock:
        _call_counters[model_key] = _call_counters.get(model_key, 0) + 1
        call_count = _call_counters[model_key]

        entry = _models.get(model_key)

        # 특징 차원 변경 시 구 버전 모델 폐기 (차원 불일치 ValueError 방지)
        if entry is not None and entry.get("version", 1) != MODEL_VERSION:
            del _models[model_key]
            entry = None

        # 재학습 조건: call_count 기반 (슬라이딩 윈도우 크기 고정 문제 회피)
        already_training = model_key in _training
        should_train = (
            not already_training
            and (
                entry is None
                or (call_count - entry.get("trained_call_count", 0)) >= RETRAIN_INTERVAL
            )
        )

        # 기존 모델 참조 확보 (학습 중에도 계속 사용)
        existing_model = entry["model"] if entry else None

        if should_train:
            _training.add(model_key)

    # ── 2단계: 재학습 필요 시 백그라운드 스레드 시작 ─────────────────────────
    if should_train:
        threading.Thread(
            target=_background_fit,
            args=(model_key, list(train_values), call_count, get_contamination()),
            daemon=True,
        ).start()

    # ── 3단계: 기존 모델 없으면 아직 학습 미완료 ─────────────────────────────
    if existing_model is None:
        return {"detected": False, "score": 0.0, "slope": 0.0, "model_ready": False}

    # ── 4단계: 탐지 (락 밖) ─────────────────────────────────────────────────
    # values[-1] == current (push 후 조회이므로), 진짜 이전값은 [-2]
    last_prev = values[-2] if len(values) >= 2 else current
    x = _make_features(
        train_values,
        current,
        last_actual=last_prev,
        raw_values=list(values),  # 원본 윈도우 → slope 계산 기준 (정제 전)
    )
    # slope — AIPrediction 기록 및 추세 분석용으로 반환
    slope = _calc_slope(list(values)[-SLOPE_WINDOW:]) if len(values) >= 2 else 0.0

    try:
        # score_samples() 한 번만 호출 — predict() 는 내부적으로 동일 연산을 반복하므로 제거.
        # sklearn IsolationForest:
        #   decision_function(X) = score_samples(X) - offset_
        #   predict(X) == -1  ⟺  decision_function(X) < 0
        #                     ⟺  score_samples(X) < offset_
        score = float(existing_model.score_samples(x)[0])
        detected = score < existing_model.offset_
    except ValueError:
        # 버전 불일치 등 차원 오류 → 모델 폐기, 다음 틱에 재학습
        with _lock:
            _models.pop(model_key, None)
        return {"detected": False, "score": 0.0, "slope": 0.0, "model_ready": False}

    return {
        "detected": detected,
        "score":    round(score, 4),
        "slope":    round(slope, 5),   # 추세 기울기 — AIPrediction.slope 에 저장
        "model_ready": True,
    }
