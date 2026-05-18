"""
ml_engine/evaluator.py — Proxy Label 기반 AI 모델 성능 평가

임계치 초과(sensor_danger / sensor_caution)를 정답 레이블로 사용.

판정 기준 (PROXY_WINDOW_MIN 분 이내 같은 device_id):
  TP : ML 알람 발생 + 이후 임계치 알람 발생  → 조기 탐지 성공
  FP : ML 알람 발생 + 임계치 알람 없음       → 오탐 후보
  FN : 임계치 알람 발생 + 이전 ML 알람 없음  → 미탐지

설계:
  - DB 쿼리는 항상 백그라운드 데몬 스레드에서만 실행
  - compute_proxy_metrics()는 캐시에서 즉시 반환 (ASGI 스레드 블로킹 없음)
  - 캐시 없음 → {'computing': True} 반환, JS가 재시도
  - 캐시 만료 → 이전 값 즉시 반환 + 백그라운드 갱신 트리거 (stale-while-revalidate)
"""
import logging
import threading
import time
from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

logger = logging.getLogger(__name__)

_ML_TYPES = {
    'ai_ml_anomaly',
    'ai_anomaly_warning',
    'ai_trend_shift',
    'ai_drift_alert',
    'ai_predictive_alert',
    'ai_predictive_warning',
    'ai_correlation',
}
_THRESHOLD_TYPES = {'sensor_danger', 'sensor_caution'}

# 즉각 탐지형 — Z-score/ChangePoint/IF/상관관계: 현재 이상을 즉시 반응
# → 10분 창으로 threshold 매칭 평가
_FAST_ML_TYPES = {
    'ai_ml_anomaly',
    'ai_anomaly_warning',
    'ai_trend_shift',
    'ai_correlation',
}
# 누적·예측형 — CUSUM(완만한 드리프트), ARIMA(미래 예측): 수십 분 선행 탐지
# → 30분 창으로 평가 (10분 창은 조기 탐지를 FP로 오분류)
_SLOW_ML_TYPES = {
    'ai_drift_alert',
    'ai_predictive_alert',
    'ai_predictive_warning',
}

PROXY_WINDOW_FAST_MIN = 10   # 즉각 탐지형 매칭 창
PROXY_WINDOW_SLOW_MIN = 30   # 누적·예측형 매칭 창
_CACHE_TTL_SEC        = 300  # 5분

# ── 캐시 상태 ─────────────────────────────────────────────
_cache:      dict = {}          # {days: {'result': dict, 'ts': float}}
_refreshing: set  = set()       # 현재 갱신 중인 days 값
_lock = threading.Lock()


def compute_proxy_metrics(days: int = 7) -> dict:
    """
    캐시에서 즉시 반환 — DB 쿼리 없음.
    캐시 없음  → {'computing': True}  (JS가 재시도)
    캐시 만료  → 이전 결과 반환 + 백그라운드 갱신 예약
    """
    now = time.monotonic()
    with _lock:
        cached = _cache.get(days)
        expired = cached and (now - cached['ts'] >= _CACHE_TTL_SEC)

        if expired and days not in _refreshing:
            _schedule_refresh(days)

        if cached:
            return cached['result']

        # 아직 한 번도 계산 안 됨
        if days not in _refreshing:
            _schedule_refresh(days)
        return {'computing': True}


def warm_cache(days: int = 7) -> None:
    """앱 시작 시 호출 — 백그라운드에서 첫 번째 캐시를 채움."""
    with _lock:
        if days not in _cache and days not in _refreshing:
            _schedule_refresh(days)


def _schedule_refresh(days: int) -> None:
    """_lock 보유 상태에서 호출. 백그라운드 스레드 시작."""
    _refreshing.add(days)
    threading.Thread(target=_refresh, args=(days,), daemon=True).start()


def _refresh(days: int) -> None:
    """백그라운드 전용 — ASGI 스레드와 무관하게 DB 쿼리 실행."""
    try:
        result = _compute(days)
        with _lock:
            _cache[days] = {'result': result, 'ts': time.monotonic()}
        logger.debug("[evaluator] cache refreshed (days=%d)", days)
    except Exception as exc:
        logger.warning("[evaluator] cache refresh failed: %s", exc)
        # 에러 상태를 캐시에 저장 — JS가 "계산 중…" 루프에 빠지지 않도록
        with _lock:
            if days not in _cache:
                _cache[days] = {
                    'result': {'computing': False, 'error': '평가 데이터를 계산하지 못했습니다.'},
                    'ts': time.monotonic() - _CACHE_TTL_SEC + 60,  # 1분 후 재시도
                }
    finally:
        # DB 커넥션 반환 — 백그라운드 스레드는 Django가 자동으로 닫아주지 않음
        try:
            from django.db import close_old_connections
            close_old_connections()
        except Exception:
            pass
        with _lock:
            _refreshing.discard(days)


def _compute(days: int) -> dict:
    from alerts.models import Alarm

    cutoff    = timezone.now() - timedelta(days=days)
    fast_win  = timedelta(minutes=PROXY_WINDOW_FAST_MIN)
    slow_win  = timedelta(minutes=PROXY_WINDOW_SLOW_MIN)

    ml_qs = Alarm.objects.filter(alarm_type__in=_ML_TYPES, created_at__gte=cutoff)
    th_qs = Alarm.objects.filter(alarm_type__in=_THRESHOLD_TYPES, created_at__gte=cutoff)

    ml_total = ml_qs.count()
    th_total = th_qs.count()

    feedback_tp   = ml_qs.filter(feedback='tp').count()
    feedback_fp   = ml_qs.filter(feedback='fp').count()
    feedback_used = feedback_tp + feedback_fp

    # ── proxy TP: 알람 유형별 창 분리 ──────────────────────────
    # 즉각 탐지형(FAST): 10분 창 — Z-score/ChangePoint/IF/상관관계
    # 누적·예측형(SLOW): 30분 창 — CUSUM drift / ARIMA predictive
    no_fb_fast = ml_qs.filter(feedback__isnull=True, alarm_type__in=_FAST_ML_TYPES)
    no_fb_slow = ml_qs.filter(feedback__isnull=True, alarm_type__in=_SLOW_ML_TYPES)

    th_after_fast = Alarm.objects.filter(
        alarm_type__in=_THRESHOLD_TYPES,
        device_id=OuterRef('device_id'),
        created_at__gte=OuterRef('created_at'),
        created_at__lte=OuterRef('created_at') + fast_win,
    )
    th_after_slow = Alarm.objects.filter(
        alarm_type__in=_THRESHOLD_TYPES,
        device_id=OuterRef('device_id'),
        created_at__gte=OuterRef('created_at'),
        created_at__lte=OuterRef('created_at') + slow_win,
    )

    proxy_tp_fast = no_fb_fast.filter(Exists(th_after_fast)).count()
    proxy_tp_slow = no_fb_slow.filter(Exists(th_after_slow)).count()
    proxy_used    = no_fb_fast.count() + no_fb_slow.count()
    proxy_tp      = proxy_tp_fast + proxy_tp_slow
    proxy_fp      = proxy_used - proxy_tp

    # ── FN: 임계치 알람 직전 fast_win(10분) 내 ML 알람 없으면 미탐지 ──
    # FN 계산에는 fast_win(10분) 사용:
    #   - threshold(sensor_type='gas') vs AI(sensor_type='co') 구조 불일치로
    #     device_id 단위 매칭만 가능. slow_win(30분) 사용 시 센서가 하루
    #     수백~천 건 AI 알람을 발생시키므로 FN≈0, Recall≈100%로 수렴해 지표가 무의미해짐.
    #   - 10분 창은 여전히 넉넉하면서 측정 신뢰도를 유지할 수 있는 최소 기준.
    ml_before_th = Alarm.objects.filter(
        alarm_type__in=_ML_TYPES,
        device_id=OuterRef('device_id'),
        created_at__gte=OuterRef('created_at') - fast_win,
        created_at__lte=OuterRef('created_at'),
    )
    fn = th_qs.filter(~Exists(ml_before_th)).count()

    tp = feedback_tp + proxy_tp
    fp = feedback_fp + proxy_fp

    total_ml  = tp + fp
    precision = tp / total_ml if total_ml > 0 else None

    # Recall: 임계치 알람 중 ML이 사전 탐지한 비율 (이벤트 기준)
    # proxy_tp는 ML 알람 단위, fn은 임계치 알람 단위 — 단위가 달라 tp/(tp+fn) 사용 불가.
    # th_caught = 직전 fast_win 이내 ML 알람이 있었던 임계치 알람 수 = th_total - fn
    th_caught = th_total - fn
    recall    = th_caught / th_total if th_total > 0 else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall else None
    )
    fp_rate = fp / total_ml if total_ml > 0 else None

    hint, hint_msg = _contamination_hint(fp_rate, recall)

    return {
        'computing':               False,
        'tp':                      tp,
        'fp':                      fp,
        'fn':                      fn,
        'precision':               _pct(precision),
        'recall':                  _pct(recall),
        'f1':                      _pct(f1),
        'fp_rate':                 _pct(fp_rate),
        'contamination_hint':      hint,
        'hint_message':            hint_msg,
        'days':                    days,
        'proxy_window_min':        PROXY_WINDOW_FAST_MIN,   # 기존 API 호환 (fast 기준)
        'proxy_window_slow_min':   PROXY_WINDOW_SLOW_MIN,
        'ml_total':                ml_total,
        'threshold_total':         th_total,
        'feedback_used':           feedback_used,
        'proxy_used':              proxy_used,
    }


def _contamination_hint(fp_rate, recall) -> tuple:
    if fp_rate is None:
        return 'unknown', '데이터 부족 — 더 많은 알람이 쌓이면 평가 가능'
    if fp_rate > 0.5:
        return 'lower', (
            f'오탐률 {_pct(fp_rate)}% — contamination을 낮추면 오탐 감소 '
            f'(현재 0.01 → 0.005 권장)'
        )
    if fp_rate < 0.1:
        return 'raise', (
            f'오탐률 {_pct(fp_rate)}% — contamination을 높이면 미탐지 감소 '
            f'(현재 0.01 → 0.02 검토)'
        )
    return 'ok', f'오탐률 {_pct(fp_rate)}% — 현재 contamination 적정 수준'


def _pct(v) -> float | None:
    if v is None:
        return None
    return round(v * 100, 1)
