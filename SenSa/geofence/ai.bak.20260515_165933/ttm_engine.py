"""
geofence/ai/ttm_engine.py — TTM 추론 엔진 (Django 통합).

[설계]
- 모듈 레벨 싱글톤 engine 인스턴스
- Lazy load: 첫 추론 시 모델 로딩 (Django 기동 시간 영향 없음)
- 이후 같은 프로세스 안에서 모델 재사용 (1~2초 추론)

[fastapi_ai 분리 → Django 통합 결정]
SenSa 현재 규모 (센서 10개, 매분 트래픽) 에서는 별도 서버 분리의 비용이
이득보다 큼. 추후 GPU 필요 / 다중 클라이언트 / 다른 ML 모델 추가 시
이 모듈 인터페이스 그대로 두고 HTTP 호출로 마이그레이션 가능.
"""
import threading

import numpy as np
import pandas as pd
import torch

from tsfm_public import (
    TinyTimeMixerForPrediction,
    TimeSeriesPreprocessor,
    TimeSeriesForecastingPipeline,
)


# ── TTM 모델 설정 ──
HF_MODEL = 'ibm-granite/granite-timeseries-ttm-r2'
CONTEXT_LENGTH = 512
FORECAST_LENGTH = 96
MIN_INPUT_LENGTH = CONTEXT_LENGTH + FORECAST_LENGTH   # 608


# ── 도메인별 이상 판정 임계 (현실 baseline 데이터 분포 기반 조정) ──
#   2026-05-14 실측 fastapi normal 분포:
#     CO  avg=14.5 max=25  H2S avg=3.1 max=10   CO2 avg=597 max=777
#     NH3 avg=10  max=25  NO2 avg=0.04 max=0.08 SO2 avg=0.19 max=0.33
#     O3  avg=0.02 max=0.04 VOC avg=0.18 max=0.49
#
#   임계 = normal max 보다 충분히 큼 + 실제 위험 농도(ACGIH/OSHA) 참조
DOMAIN_THRESHOLDS = {
    'co':  {'CAUTION': 25,   'DANGER': 200,  'RESIDUAL_ABS_LIMIT': 20,  'SIGMA_K': 4},
    'h2s': {'CAUTION': 10,   'DANGER': 100,  'RESIDUAL_ABS_LIMIT': 5,   'SIGMA_K': 4},
    'co2': {'CAUTION': 1000, 'DANGER': 5000, 'RESIDUAL_ABS_LIMIT': 100, 'SIGMA_K': 4},
    'nh3': {'CAUTION': 30,   'DANGER': 100,  'RESIDUAL_ABS_LIMIT': 15,  'SIGMA_K': 4},
    'no2': {'CAUTION': 3,    'DANGER': 30,   'RESIDUAL_ABS_LIMIT': 1,   'SIGMA_K': 4},
    'so2': {'CAUTION': 5,    'DANGER': 50,   'RESIDUAL_ABS_LIMIT': 3,   'SIGMA_K': 4},
    'o3':  {'CAUTION': 0.3,  'DANGER': 1,    'RESIDUAL_ABS_LIMIT': 0.2, 'SIGMA_K': 4},
    'voc': {'CAUTION': 100,  'DANGER': 1000, 'RESIDUAL_ABS_LIMIT': 50,  'SIGMA_K': 4},
    'o2':  {'CAUTION': 23,   'DANGER': 25,   'RESIDUAL_ABS_LIMIT': 1,   'SIGMA_K': 4},
}
DEFAULT_THRESH = {'CAUTION': 25, 'DANGER': 200, 'RESIDUAL_ABS_LIMIT': 20, 'SIGMA_K': 4}

# forecast 96개 중 N개 이상 임계 초과 시 warn
# 2026-05-14 시뮬레이션 검증:
#   - 정상 데이터: 모든 sensor 의 임계 초과 0개 (안전 마진 큼)
#   - NH3 80ppm spike 50건 주입: 96 중 21개 초과 (점진 회귀)
#   → 15 가 정상=안 발동, spike=발동 균형점
FORECAST_WARN_COUNT = 15


class TTMEngine:
    """TTM 추론 엔진 — lazy load + 싱글톤."""

    def __init__(self):
        self._model = None
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """첫 호출 시 모델 로딩. 스레드 안전."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:   # double-check
                return
            print(f"[TTM] 모델 로딩 시작 (device={self._device})...")
            self._model = (
                TinyTimeMixerForPrediction.from_pretrained(HF_MODEL)
                .to(self._device)
                .eval()
            )
            print(f"[TTM] 모델 로딩 완료")

    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str:
        return self._device

    def predict(self, values: list, gas_type: str = 'co') -> dict:
        """시계열 → forecast + 잔차 + anomaly 판정.

        Args:
            values: 시계열 측정값. 길이 >= 608. Tail 608 만 사용.
            gas_type: 도메인 임계 적용용.

        Returns:
            predictions, residuals, residual_*, anomaly 등 포함.
        """
        self._ensure_loaded()

        if len(values) < MIN_INPUT_LENGTH:
            raise ValueError(
                f"입력 길이 부족: {len(values)} < {MIN_INPUT_LENGTH}"
            )

        # Tail 608 만 사용
        values = values[-MIN_INPUT_LENGTH:]
        context = values[:CONTEXT_LENGTH]
        actual = np.array(values[CONTEXT_LENGTH:], dtype=float)

        # DataFrame 구성 (timestamp 더미 — 1분 간격)
        timestamps = pd.date_range(
            start='2000-01-01', periods=CONTEXT_LENGTH, freq='1min'
        )
        df = pd.DataFrame({
            'timestamp': timestamps,
            'series_id': 'default',
            gas_type: context,
        })

        # Preprocessor + Pipeline
        tsp = TimeSeriesPreprocessor(
            timestamp_column='timestamp',
            id_columns=['series_id'],
            target_columns=[gas_type],
            context_length=CONTEXT_LENGTH,
            prediction_length=FORECAST_LENGTH,
            scaling=True,
            scaler_type='standard',
        )
        tsp.train(df)
        pipeline = TimeSeriesForecastingPipeline(
            model=self._model,
            feature_extractor=tsp,
            device=self._device,
            batch_size=1,
        )

        fc = pipeline(df)
        preds = np.asarray(fc[f'{gas_type}_prediction'].iloc[0], dtype=float)

        # 잔차
        residuals = actual - preds
        residuals_centered = residuals - residuals.mean()

        residual_std = float(np.std(residuals_centered))
        residual_mean = float(residuals.mean())
        residual_max_abs = float(np.max(np.abs(residuals)))
        residual_recent = float(residuals_centered[-1])

        # 임계 적용
        thresh = DOMAIN_THRESHOLDS.get(gas_type.lower(), DEFAULT_THRESH)
        sigma_thresh = thresh['SIGMA_K'] * residual_std

        anomaly_mask = (
            (np.abs(residuals_centered) > sigma_thresh) |
            (np.abs(residuals) > thresh['RESIDUAL_ABS_LIMIT']) |
            (actual >= thresh['CAUTION'])
        )
        anomaly_count = int(anomaly_mask.sum())

        forecast_exceed = int((preds >= thresh['CAUTION']).sum())
        forecast_warn = forecast_exceed >= FORECAST_WARN_COUNT

        return {
            'predictions': preds.tolist(),
            'residuals': residuals.tolist(),
            'residuals_centered': residuals_centered.tolist(),
            'residual_recent': residual_recent,
            'residual_std': residual_std,
            'residual_mean': residual_mean,
            'residual_max_abs': residual_max_abs,
            'anomaly': bool(anomaly_count > 0),
            'anomaly_count': anomaly_count,
            'forecast_warn': bool(forecast_warn),
            'forecast_exceed_count': forecast_exceed,
            'thresholds_used': thresh,
        }


# 모듈 레벨 싱글톤
engine = TTMEngine()
