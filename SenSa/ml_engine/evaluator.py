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

탐지기별 breakdown (per_detector):
  알람 타입 → 탐지기 매핑
    ai_ml_anomaly      → Isolation Forest (단독) 또는 앙상블 (2+ 탐지기)
    ai_anomaly_warning → Z-score
    ai_trend_shift     → Change Point
    ai_drift_alert     → CUSUM (누적 드리프트)
    ai_predictive_*    → ARIMA 예측
    ai_correlation     → 다중 센서 상관관계
  주의: ai_ml_anomaly 는 IF 단독과 앙상블이 섞여 있어 단일 탐지기와 1:1 대응 불가.
  window 컬럼: 'fast'(10분 창) 또는 'slow'(30분 창) — 평가 창 크기 표시
"""
import logging
import threading
import time
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
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


def _apply_contamination_hint(hint: str, fp_rate_pct: float | None) -> None:
    """
    evaluator 힌트에 따라 IF contamination 을 ±0.005 씩 점진적으로 조정.

    호출: _refresh() 내에서 백그라운드 스레드 전용.
    변경 단위(_CONTAMINATION_STEP=0.005) 를 1회에 하나씩만 조정하여 진동 방지.
    조정 내역은 DEBUG 로그로 기록.

    hint='ok' 이거나 fp_rate_pct 가 None 이면 아무것도 하지 않음.
    """
    if hint not in ('lower', 'raise') or fp_rate_pct is None:
        return
    try:
        from ml_engine import isolation_forest
        cur = isolation_forest.get_contamination()
        step = isolation_forest._CONTAMINATION_STEP

        if hint == 'lower':
            new_v = max(isolation_forest.CONTAMINATION_MIN, cur - step)
        else:  # 'raise'
            new_v = min(isolation_forest.CONTAMINATION_MAX, cur + step)

        if abs(new_v - cur) < 1e-6:
            return   # 이미 한계치 — 변경 없음

        isolation_forest.set_contamination(new_v)
        logger.info(
            "[evaluator] contamination 자동 조정: %.4f → %.4f (hint=%s, fp_rate=%.1f%%)",
            cur, new_v, hint, fp_rate_pct,
        )
    except Exception as exc:
        logger.debug("[evaluator] contamination 자동 조정 실패: %s", exc)


def _refresh(days: int) -> None:
    """백그라운드 전용 — ASGI 스레드와 무관하게 DB 쿼리 실행."""
    try:
        result = _compute(days)

        # ── contamination 자동 조정 ────────────────────────────
        # fp_rate 힌트에 따라 IF contamination 을 ±0.005 점진 조정.
        # days=7 기준 데이터에서만 적용 (짧은 기간은 노이즈 가능성).
        if days == 7:
            _apply_contamination_hint(
                result.get('contamination_hint', 'ok'),
                result.get('fp_rate'),
            )

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
    from alerts.models import Alarm, AIPrediction

    cutoff    = timezone.now() - timedelta(days=days)
    fast_win  = timedelta(minutes=PROXY_WINDOW_FAST_MIN)
    slow_win  = timedelta(minutes=PROXY_WINDOW_SLOW_MIN)

    ml_qs = Alarm.objects.filter(alarm_type__in=_ML_TYPES, created_at__gte=cutoff)
    th_qs = Alarm.objects.filter(alarm_type__in=_THRESHOLD_TYPES, created_at__gte=cutoff)

    ml_total = ml_qs.count()
    th_total = th_qs.count()

    # ── 공통 서브쿼리 (재사용) ──────────────────────────────────
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
    # 전력-가스 교차 상관관계 전용 — related_device_id(가스 센서) 기준 threshold 매칭
    th_after_fast_corr = Alarm.objects.filter(
        alarm_type__in=_THRESHOLD_TYPES,
        device_id=OuterRef('related_device_id'),
        created_at__gte=OuterRef('created_at'),
        created_at__lte=OuterRef('created_at') + fast_win,
    )

    # ── proxy TP: 알람 유형별 창 분리 ──────────────────────────
    # 즉각 탐지형(FAST): 10분 창 — Z-score/ChangePoint/IF/상관관계
    # 누적·예측형(SLOW): 30분 창 — CUSUM drift / ARIMA predictive
    no_fb_fast = ml_qs.filter(alarm_type__in=_FAST_ML_TYPES)
    no_fb_slow = ml_qs.filter(alarm_type__in=_SLOW_ML_TYPES)

    # ai_correlation + sensor_type='power' 는 크로스 디바이스 매칭 적용
    #   related_device_id 있는 신규 알람 → th_after_fast_corr (가스 센서 기준)
    #   related_device_id 없는 구형 알람 → th_after_fast (전력 센서 기준, 기존 동작 유지)
    fast_corr_power     = no_fb_fast.filter(alarm_type='ai_correlation', sensor_type='power')
    fast_other          = no_fb_fast.exclude(Q(alarm_type='ai_correlation') & Q(sensor_type='power'))

    tp_fast_other       = fast_other.filter(Exists(th_after_fast)).count()
    tp_fast_corr_new    = fast_corr_power.exclude(related_device_id='').filter(Exists(th_after_fast_corr)).count()
    tp_fast_corr_old    = fast_corr_power.filter(related_device_id='').filter(Exists(th_after_fast)).count()

    proxy_tp_fast = tp_fast_other + tp_fast_corr_new + tp_fast_corr_old
    proxy_tp_slow = no_fb_slow.filter(Exists(th_after_slow)).count()
    proxy_used    = no_fb_fast.count() + no_fb_slow.count()
    proxy_tp      = proxy_tp_fast + proxy_tp_slow
    proxy_fp      = proxy_used - proxy_tp

    # ── 탐지기별 breakdown ──────────────────────────────────────
    per_detector = _compute_per_type(ml_qs, th_after_fast, th_after_slow, th_after_fast_corr)

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

    tp = proxy_tp
    fp = proxy_fp

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

    # 현재 런타임 contamination 값
    try:
        from ml_engine.isolation_forest import get_contamination as _gc
        current_contamination = round(_gc(), 4)
    except Exception:
        current_contamination = None

    # ── AIPrediction 기반 ARIMA 예측 정확도 ──────────────────
    # proxy와 달리 ARIMA 예측이 실제로 임계치를 넘었는지를 직접 측정.
    # proxy는 "AI 알람 후 threshold 알람 발생" 여부이고,
    # arima_accuracy는 "ARIMA가 예측한 값이 실제로 발생했는지" 로 별도 지표.
    # COUNT + CASE WHEN 1회 쿼리로 4개 집계 (기존 쿼리 4회 → 1회)
    arima_agg = (
        AIPrediction.objects
        .filter(created_at__gte=cutoff)
        .aggregate(
            total=Count('id'),
            success=Count('id', filter=Q(result='success')),
            failure=Count('id', filter=Q(result='failure')),
            pending=Count('id', filter=Q(result='pending')),
        )
    )
    arima_total   = arima_agg['total']
    arima_success = arima_agg['success']
    arima_failure = arima_agg['failure']
    arima_pending = arima_agg['pending']
    arima_acc     = (
        round(arima_success / (arima_success + arima_failure) * 100, 1)
        if (arima_success + arima_failure) > 0
        else None
    )

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
        'current_contamination':   current_contamination,
        'days':                    days,
        'proxy_window_min':        PROXY_WINDOW_FAST_MIN,
        'proxy_window_slow_min':   PROXY_WINDOW_SLOW_MIN,
        'ml_total':                ml_total,
        'threshold_total':         th_total,
        'proxy_used':              proxy_used,
        # ── 탐지기별 세부 precision (breakdown) ──────────────
        # 각 alarm_type별 count / tp / fp / precision
        # ai_ml_anomaly 는 IF 단독 + 앙상블이 혼재 → 단일 탐지기와 1:1 대응 아님.
        # 상대적으로 precision 이 낮은 타입 → 해당 탐지기 파라미터 우선 점검.
        'per_detector':            per_detector,
        # ARIMA 예측 정확도 (AIPrediction 테이블 직접 집계)
        'arima_total':             arima_total,
        'arima_success':           arima_success,
        'arima_failure':           arima_failure,
        'arima_pending':           arima_pending,
        'arima_accuracy':          arima_acc,
    }


def _compute_per_type(ml_qs, th_after_fast, th_after_slow, th_after_fast_corr=None) -> dict:
    """
    alarm_type 별 count / tp / fp / precision 집계.

    각 타입이 FAST(10분) 또는 SLOW(30분) 창을 사용하는지 함께 반환.
    총 14개 COUNT 쿼리 추가 (7 타입 × 2: count + tp) → 백그라운드 전용.

    ai_correlation + sensor_type='power':
      related_device_id 있는 신규 알람 → th_after_fast_corr (가스 센서 기준 크로스 매칭)
      related_device_id 없는 구형 알람 → th_after_fast (전력 센서 기준, 기존 동작 유지)
      ai_correlation + sensor_type='gas' → th_after_fast (동일 디바이스 기준 기존 동작 유지)

    반환 형식:
      {
        'ai_ml_anomaly': {
            'count': int, 'tp': int, 'fp': int,
            'precision': float|None,  # 0.0~100.0
            'window': 'fast'|'slow',
        },
        ...
      }
    """
    result = {}
    for alarm_type in sorted(_ML_TYPES):
        use_slow  = alarm_type in _SLOW_ML_TYPES
        th_exists = th_after_slow if use_slow else th_after_fast

        qs    = ml_qs.filter(alarm_type=alarm_type)
        count = qs.count()

        if count == 0:
            result[alarm_type] = {
                'count': 0, 'tp': 0, 'fp': 0,
                'precision': None,
                'window': 'slow' if use_slow else 'fast',
            }
            continue

        if alarm_type == 'ai_correlation' and th_after_fast_corr is not None:
            # 전력-가스 교차: related_device_id 유무로 분기
            corr_power_new = qs.filter(sensor_type='power').exclude(related_device_id='')
            corr_power_old = qs.filter(sensor_type='power', related_device_id='')
            corr_gas       = qs.exclude(sensor_type='power')
            tp = (
                corr_power_new.filter(Exists(th_after_fast_corr)).count() +
                corr_power_old.filter(Exists(th_after_fast)).count() +
                corr_gas.filter(Exists(th_exists)).count()
            )
        else:
            tp = qs.filter(Exists(th_exists)).count()

        fp = count - tp
        result[alarm_type] = {
            'count':     count,
            'tp':        tp,
            'fp':        fp,
            'precision': _pct(tp / count) if count > 0 else None,
            'window':    'slow' if use_slow else 'fast',
        }
    return result


def _contamination_hint(fp_rate, recall) -> tuple:
    if fp_rate is None:
        return 'unknown', '데이터 부족 — 더 많은 알람이 쌓이면 평가 가능'

    # 현재 런타임 contamination 값을 동적으로 조회
    try:
        from ml_engine.isolation_forest import get_contamination, _CONTAMINATION_STEP, CONTAMINATION_MIN, CONTAMINATION_MAX
        cur       = get_contamination()
        lower_val = max(CONTAMINATION_MIN, round(cur - _CONTAMINATION_STEP, 4))
        raise_val = min(CONTAMINATION_MAX, round(cur + _CONTAMINATION_STEP, 4))
    except Exception:
        cur, lower_val, raise_val = 0.03, 0.025, 0.035

    if fp_rate > 0.5:
        return 'lower', (
            f'오탐률 {_pct(fp_rate)}% — contamination을 낮추면 오탐 감소 '
            f'(현재 {cur:.4f} → {lower_val:.4f} 권장)'
        )
    if fp_rate < 0.1:
        return 'raise', (
            f'오탐률 {_pct(fp_rate)}% — contamination을 높이면 미탐지 감소 '
            f'(현재 {cur:.4f} → {raise_val:.4f} 검토)'
        )
    return 'ok', f'오탐률 {_pct(fp_rate)}% — 현재 contamination 적정 수준 (현재 {cur:.4f})'


def _pct(v) -> float | None:
    if v is None:
        return None
    return round(v * 100, 1)
