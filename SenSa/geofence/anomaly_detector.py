"""
geofence/anomaly_detector.py — 센서 이상 신호 판정.

[v4 — TTM 완전 제거 (5차 세션 C′-3b-1)]
이전 v3 에서 TTM zero-shot 추론을 1차 경로로 사용했으나,
Isolation Forest 기반 신규 분석기 (geofence/if_analyzer.py, C′-3b-2) 도입에 따라 폐기.
TTM 입력 부족 시 fallback 으로만 동작하던 v2 단순 평균 차이 로직이
이제 단일 경로로 동작.

[인터페이스 무수정]
get_recent_residual(device, gas_type) → float
has_anomaly(device, gas_type, threshold=None) → bool
호출 측 (zone_lifecycle.check_tier_upgrade) 코드 변경 불필요.
"""
from datetime import timedelta
from django.db.models import Avg
from django.utils import timezone


# ── 잔차 분석 윈도우 ──
LOOKBACK_RECENT_SEC = 300       # 최근 5분
LOOKBACK_BASELINE_SEC = 1800    # 직전 30분

# ── has_anomaly 임계 (도메인별, 이전 ttm_engine 의 RESIDUAL_ABS_LIMIT 값 inline) ──
# 2026-05-14 실측 baseline 분포 기반. 임계 = normal max 보다 충분히 큼.
CONFIRM_RESIDUAL_THRESH = {
    'co':  20,
    'h2s': 5,
    'co2': 100,
    'nh3': 15,
    'no2': 1,
    'so2': 3,
    'o3':  0.2,
    'voc': 50,
    'o2':  1,
}
DEFAULT_RESIDUAL_THRESH = 20


def get_recent_residual(device, gas_type: str) -> float:
    """센서의 최근 잔차 (v2 simple residual).

    잔차 = 최근 5분 평균 − 직전 25분 평균.
    데이터 부족 시 0.0.

    Returns:
        잔차 (부호 포함). 호출 측 has_anomaly 가 abs() 적용.
    """
    from devices.models import SensorData

    field = gas_type.lower()
    now = timezone.now()
    recent_start = now - timedelta(seconds=LOOKBACK_RECENT_SEC)
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


def has_anomaly(device, gas_type: str, threshold: float = None) -> bool:
    """센서 이상 패턴 여부.

    threshold 미지정 시 도메인별 CONFIRM_RESIDUAL_THRESH 사용.
    zone_lifecycle.check_tier_upgrade 가 이웃 센서 anomaly 판정에 사용.
    """
    if threshold is None:
        threshold = CONFIRM_RESIDUAL_THRESH.get(
            gas_type.lower(),
            DEFAULT_RESIDUAL_THRESH,
        )
    return abs(get_recent_residual(device, gas_type)) > threshold
