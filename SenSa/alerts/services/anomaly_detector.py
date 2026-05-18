"""
alerts/services/anomaly_detector.py — ARIMA 기반 센서 이상 탐지.

목적:
  기존 고정 임계치(classifiers.py)는 절대값이 임계치를 넘어야 탐지함.
  ARIMA 는 '과거 패턴 대비 이탈' 을 잡아 임계치 도달 전 조기 경보를 제공.

Public API:
  detect_anomaly(device_id, sensor_type, value) → bool
    True  : 패턴 이탈 탐지 (caution 으로 상향 권장)
    False : 정상 또는 cold-start / 오류 → 기존 판정 유지

내부 구조:
  - _ArimaStore  : 장비+센서 조합별 모델 캐시 (메모리, 프로세스 수명)
  - _fit_model   : statsmodels ARIMA fit (백그라운드 Celery 또는 동기 fallback)
  - _infer       : 잔차(residual) 3σ 초과 여부 판정

제약:
  - statsmodels, numpy 필요 (pip install statsmodels numpy)
  - pmdarima 설치 시 auto_arima 로 자동 p/q 탐색 — 없으면 기본 (1,1,1) 사용
  - 장비별 모델은 메모리에만 저장. 서버 재시작 시 cold-start 재발생 (정상)
  - 학습에 필요한 최소 샘플: MIN_TRAIN_SAMPLES (기본 60개, 약 1분치)

연동 위치 (sensor_evaluator.py):
  classify_gas / classify_power 가 'normal' 반환 시에만 호출.
  True 반환 시 observed_status 를 'caution' 으로 격상.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 상수
# ═══════════════════════════════════════════════════════════

# 학습에 필요한 최소 샘플 수 (부족하면 cold-start → False 반환)
MIN_TRAIN_SAMPLES = 60

# 슬라이딩 윈도우 크기 (메모리 제한)
WINDOW_SIZE = 500

# 잔차 이상 탐지 기준 — abs(residual) > SIGMA_THRESHOLD * σ
SIGMA_THRESHOLD = 3.0

# 모델 재학습 주기 (초). 이 시간 이상 지나면 재fit.
REFIT_INTERVAL_SEC = 600  # 10분

# ARIMA 기본 차수 (p, d, q)
# pmdarima 없으면 고정값 사용
DEFAULT_ORDER = (1, 1, 1)


# ═══════════════════════════════════════════════════════════
# 내부 상태 저장소 (프로세스 메모리)
# ═══════════════════════════════════════════════════════════

class _DeviceStore:
    """장비 1개 + 센서 1종의 ARIMA 상태."""

    __slots__ = (
        'buffer',      # deque[float] — 슬라이딩 윈도우
        'model',       # fitted ARIMAResults | None
        'residual_std',# float — 학습 시점 잔차 σ
        'last_fit_at', # float — 마지막 fit 시각 (time.time())
        'lock',        # threading.Lock
        'fitting',     # bool — fit 진행 중 (중복 방지)
    )

    def __init__(self):
        self.buffer       = deque(maxlen=WINDOW_SIZE)
        self.model        = None
        self.residual_std = None
        self.last_fit_at  = 0.0
        self.lock         = threading.Lock()
        self.fitting      = False


# key: (device_id, sensor_type)
_store: dict[tuple[str, str], _DeviceStore] = defaultdict(_DeviceStore)
_store_lock = threading.Lock()


def _get_store(device_id: str, sensor_type: str) -> _DeviceStore:
    key = (device_id, sensor_type)
    with _store_lock:
        return _store[key]


# ═══════════════════════════════════════════════════════════
# ARIMA fit
# ═══════════════════════════════════════════════════════════

def _fit_model(ds: _DeviceStore) -> None:
    """
    슬라이딩 윈도우로 ARIMA 재학습.
    ds.lock 획득 후 호출할 것.
    """
    try:
        data = np.array(list(ds.buffer), dtype=float)

        # pmdarima 있으면 자동 차수 탐색, 없으면 기본값
        try:
            from pmdarima import auto_arima  # type: ignore
            result = auto_arima(
                data,
                start_p=0, max_p=3,
                start_q=0, max_q=3,
                d=None,            # ADF 검정으로 자동 결정
                seasonal=False,
                error_action='ignore',
                suppress_warnings=True,
                stepwise=True,
            )
            # pmdarima 결과 → statsmodels 형태로 통일
            fitted = result
            residuals = result.resid()
        except ImportError:
            from statsmodels.tsa.arima.model import ARIMA  # type: ignore
            fitted = ARIMA(data, order=DEFAULT_ORDER).fit()
            residuals = fitted.resid

        std = float(np.std(residuals))
        if std < 1e-9:
            std = 1e-9  # 0 나눗셈 방지

        ds.model        = fitted
        ds.residual_std = std
        ds.last_fit_at  = time.time()

    except Exception as exc:
        logger.warning("ARIMA fit 실패 [%s]: %s", ds, exc)
    finally:
        ds.fitting = False


def _maybe_refit_async(ds: _DeviceStore) -> None:
    """재학습 필요 시 별도 스레드로 fit (메인 스레드 차단 없음)."""
    now = time.time()
    if ds.fitting:
        return
    if (now - ds.last_fit_at) < REFIT_INTERVAL_SEC and ds.model is not None:
        return
    if len(ds.buffer) < MIN_TRAIN_SAMPLES:
        return

    ds.fitting = True
    t = threading.Thread(target=_fit_model, args=(ds,), daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════════
# 잔차 기반 이상 판정
# ═══════════════════════════════════════════════════════════

def _infer(ds: _DeviceStore, value: float) -> bool:
    """
    현재 값의 잔차가 3σ 초과인지 판정.
    모델 없으면 False (cold-start).
    """
    if ds.model is None or ds.residual_std is None:
        return False

    try:
        # 1-step ahead 예측
        try:
            # pmdarima ARIMAResults
            pred = float(ds.model.predict(n_periods=1)[0])
        except AttributeError:
            # statsmodels ARIMAResults
            pred = float(ds.model.forecast(steps=1).iloc[0])

        residual = abs(value - pred)
        return residual > SIGMA_THRESHOLD * ds.residual_std

    except Exception as exc:
        logger.debug("ARIMA inference 실패: %s", exc)
        return False


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════

def detect_anomaly(device_id: str, sensor_type: str, value: float) -> bool:
    """
    센서 값 1개를 버퍼에 추가 후 ARIMA 잔차 이상 여부 반환.

    Args:
        device_id   : 장비 식별자 (SenSa device_id 필드)
        sensor_type : 'gas' | 'power' | 기타
        value       : 대표 스칼라값
                      gas   → CO ppm (worst 종 값 or 대표값)
                      power → watt

    Returns:
        True  — 패턴 이탈 (caution 격상 권장)
        False — 정상 / cold-start / 오류

    Side-effect:
        버퍼에 value 추가, 필요 시 백그라운드 재학습 트리거.
    """
    ds = _get_store(device_id, sensor_type)

    with ds.lock:
        ds.buffer.append(float(value))
        _maybe_refit_async(ds)

        if len(ds.buffer) < MIN_TRAIN_SAMPLES:
            # cold-start — 학습 데이터 부족
            return False

        return _infer(ds, float(value))
