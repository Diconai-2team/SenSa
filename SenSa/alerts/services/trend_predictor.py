"""
alerts/services/trend_predictor.py — IsolationForest 기반 추세 예측 엔진

목적:
  최근 N개 데이터로 IsolationForest 학습 + 선형 추세 계산.
  추세가 지속될 경우 임계치 초과 예상 시 AI 예측 알람 생성.
  이후 실제 데이터로 예측 성공/실패 검증.

Public API:
  predict_trend(device_id, sensor_key, value, threshold) -> dict | None
    None    : 예측 없음 (cold-start / 추세 미달)
    dict    : 예측 정보 { predicted_ticks, confidence, ... }

  verify_predictions(device_id, sensor_key, value, threshold)
    : 미결 예측들의 성공/실패 검증

설계:
  - IsolationForest : 이상치 점수(anomaly score) 계산
  - 선형회귀(numpy) : 추세(기울기) 계산
  - 두 조건 모두 충족 시 예측 알람 발행
  - AIPrediction 모델에 예측 기록 저장
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from datetime import timedelta

import numpy as np
from django.utils import timezone
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 상수
# ═══════════════════════════════════════════════════════════

# 학습에 필요한 최소 샘플
MIN_TRAIN_SAMPLES = 70

# 슬라이딩 윈도우 크기
WINDOW_SIZE = 200

# IsolationForest 이상 점수 임계치 (낮을수록 이상)
# [정제 후 조정] _fit 의 MAD outlier 제거로 모델이 정상 분포만 학습 →
# 진짜 spike 의 if_score 는 -0.4 이하로 매우 낮음.
# 임계를 -0.3 으로 올려 가벼운 변동은 무시.
IF_SCORE_THRESHOLD = -0.3

# 선형 추세 기울기 임계치 — 이 이상 증가 추세면 예측 대상
# [정제 후 조정] GAS_EVENTS 점프 (6틱 지속) 의 slope ~0.27, 시나리오 spike ~1.87 →
# 0.5 로 올려 가벼운 transient 점프 제외, 진짜 누출 ramp-up 만 검출.
SLOPE_THRESHOLD = 0.5

# 예측 후 몇 틱 안에 임계치 초과해야 성공으로 볼지
PREDICTION_WINDOW_TICKS = 60  # 60틱으로 여유 확대

# 모델 재학습 주기 (건수 기준)
REFIT_EVERY_N = 20


# ═══════════════════════════════════════════════════════════
# 장비별 상태 저장소
# ═══════════════════════════════════════════════════════════

class _SensorStore:
    __slots__ = ('buffer', 'model', 'tick', 'last_fit_tick', 'lock')

    def __init__(self):
        self.buffer       = deque(maxlen=WINDOW_SIZE)
        self.model        = None   # IsolationForest
        self.tick         = 0
        self.last_fit_tick = 0
        self.lock         = threading.Lock()


_store: dict[tuple[str, str], _SensorStore] = defaultdict(_SensorStore)
_store_lock = threading.Lock()


def _get_store(device_id: str, sensor_key: str) -> _SensorStore:
    key = (device_id, sensor_key)
    with _store_lock:
        return _store[key]


# ═══════════════════════════════════════════════════════════
# IsolationForest fit
# ═══════════════════════════════════════════════════════════

def _fit(ss: _SensorStore) -> None:
    """IsolationForest 학습. MAD 기반 outlier 제거로 정상 분포만 학습.

    배경:
        - buffer 에는 정상값 + GAS_EVENTS 점프 + 시나리오 spike 가 섞임
        - 그대로 학습하면 모델이 outlier 도 정상으로 학습 → false positive 증가
    정제 방식:
        - Modified Z-Score (MAD 기반) 으로 outlier 제거
        - MAD = Median Absolute Deviation (robust statistic, mean/std 보다 안정적)
        - |modified_z| >= 3.5 → outlier
    """
    data_raw = np.array(list(ss.buffer))

    # MAD 기반 outlier 제거
    median = np.median(data_raw)
    mad = np.median(np.abs(data_raw - median))
    if mad > 1e-6:
        modified_z = 0.6745 * (data_raw - median) / mad
        clean = data_raw[np.abs(modified_z) < 3.5]
    else:
        # 데이터 변동 거의 없음 → outlier 판별 불가, 전체 사용
        clean = data_raw

    # 정상 데이터 부족 시 학습 skip (이전 모델 stale 유지)
    if len(clean) < int(MIN_TRAIN_SAMPLES * 0.7):
        return

    data = clean.reshape(-1, 1)
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,  # 5% 이상치 가정 (정제 후 모델 학습)
        random_state=42,
    )
    model.fit(data)
    ss.model = model
    ss.last_fit_tick = ss.tick


def _get_slope(values: list[float]) -> float:
    """최근 N개 값의 선형 추세 기울기 반환."""
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    coeffs = np.polyfit(x, y, 1)
    return float(coeffs[0])  # 기울기


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════

def predict_trend(device_id: str, sensor_key: str,
                  value: float, threshold: float) -> dict | None:
    """
    현재값을 버퍼에 추가 후 IsolationForest + 추세 분석으로 예측.

    Args:
        device_id  : 장비 ID
        sensor_key : 센서 종류 (예: 'co', 'watt')
        value      : 현재 측정값
        threshold  : 임계치 (caution 기준)

    Returns:
        None — 예측 없음
        dict — {
            'predicted_ticks': int,   # 몇 틱 후 초과 예상
            'predicted_value': float, # 예상 도달값
            'if_score': float,        # IsolationForest 이상 점수
            'slope': float,           # 추세 기울기
        }
    """
    ss = _get_store(device_id, sensor_key)

    with ss.lock:
        ss.buffer.append(float(value))
        ss.tick += 1

        # cold-start
        if len(ss.buffer) < MIN_TRAIN_SAMPLES:
            return None

        # 재학습 필요 시
        if ss.model is None or (ss.tick - ss.last_fit_tick) >= REFIT_EVERY_N:
            _fit(ss)

        # IsolationForest 이상 점수
        arr = np.array([[float(value)]])
        if_score = float(ss.model.score_samples(arr)[0])

        # 선형 추세 (최근 30개)
        recent = list(ss.buffer)[-30:]
        slope = _get_slope(recent)

        # 예측 조건: 이상 점수 낮고 + 증가 추세
        if if_score > IF_SCORE_THRESHOLD or slope < SLOPE_THRESHOLD:
            return None

        # 몇 틱 후 임계치 초과?
        if slope <= 0:
            return None

        ticks_to_threshold = (threshold - value) / slope
        if ticks_to_threshold <= 0 or ticks_to_threshold > PREDICTION_WINDOW_TICKS:
            return None

        predicted_value = value + slope * ticks_to_threshold

        return {
            'predicted_ticks': int(ticks_to_threshold),
            'predicted_value': round(predicted_value, 3),
            'if_score': round(if_score, 4),
            'slope': round(slope, 5),
        }


def verify_predictions(device_id: str, sensor_key: str,
                       value: float, threshold: float) -> None:
    """
    미결 AIPrediction 중 마감 틱이 지난 것의 성공/실패 검증.
    devices/views.py 에서 매 틱 호출.
    """
    from alerts.models import AIPrediction

    now = timezone.now()
    # 이 장비+센서의 미결 예측
    pending = AIPrediction.objects.filter(
        device_id=device_id,
        sensor_key=sensor_key,
        result='pending',
        expires_at__lte=now,
    )
    for pred in pending:
        if value >= threshold:
            pred.result = 'success'
            logger.info("AI예측 성공 [%s/%s] value=%.3f >= threshold=%.3f",
                        device_id, sensor_key, value, threshold)
        else:
            pred.result = 'failure'
            logger.info("AI예측 실패 [%s/%s] value=%.3f < threshold=%.3f",
                        device_id, sensor_key, value, threshold)
        pred.save(update_fields=['result'])
