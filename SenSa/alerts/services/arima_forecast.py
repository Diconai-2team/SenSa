"""
ARIMA forecast — 4차 프로젝트 1단계 (AI 이상탐지) 4. 베이스라인 모델 구축.

[DEPRECATED] dashboard/views.py 에서의 사용이 ml_engine.arima_forecaster.get_forecast_values()
로 통합되었습니다. 이 파일은 레거시 참조용으로만 보관됩니다.

  이전: alerts.services.arima_forecast.arima_forecast() — ARIMA(1,1,0), 매 호출 학습 (캐시 없음)
  현재: ml_engine.arima_forecaster.get_forecast_values() — ARIMA(1,1,1), AI 파이프라인 캐시 공유

ARIMA(1,1,0): 가장 단순한 ARIMA 베이스라인.
  - AR 차수 1: 직전 1개 값의 자기회귀
  - 1차 차분: 비정상 시계열 → 정상 시계열 (산업 측정값에 적합)
  - MA 차수 0: 이동평균 미사용 (단순화)

statsmodels 미설치 시 graceful 처리 — 호출자가 fallback (선형 외삽) 으로 자동 전환.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# statsmodels 가용성 — import 실패 시 graceful
try:
    from statsmodels.tsa.arima.model import ARIMA
    ARIMA_AVAILABLE = True
except ImportError:
    ARIMA_AVAILABLE = False
    logger.warning(
        'statsmodels 미설치 — ARIMA forecast 비활성. '
        'pip install statsmodels 로 설치 권장.'
    )


def arima_forecast(values, horizon=60, order=(1, 1, 0)):
    """
    ARIMA forecast.

    Args:
        values: 최근 시계열 값 list (오래된 → 최근 순서)
        horizon: 미래 N 틱 예측
        order: (p, d, q) — 기본 (1,1,0)

    Returns:
        list[float]: 예측 시계열, 길이 horizon
        None: statsmodels 미설치 / 데이터 부족 / fit 실패
    """
    if not ARIMA_AVAILABLE:
        return None
    if len(values) < 10:
        # ARIMA(1,1,0) 최소 데이터 — 차분 후 9개 이상 필요
        return None

    try:
        model = ARIMA(values, order=order)
        fitted = model.fit()
        forecast = fitted.forecast(steps=horizon)
        return [float(v) for v in forecast]
    except Exception as e:
        logger.debug(f'ARIMA fit 실패: {e}')
        return None
