# SenSa AI 성능 향상 분석 보고서

> 목적: 기능 추가가 아닌 **기존 지표의 신뢰성 향상 + 탐지 정확도 개선**  
> 분석 기준: 실제 코드 라인 지목 + 수치 근거

---

## 목차

1. [현재 AI 평가 지표 해석](#1-현재-ai-평가-지표-해석)
2. [문제점 진단 (코드 레벨)](#2-문제점-진단-코드-레벨)
3. [개선 방안 (우선순위 순)](#3-개선-방안-우선순위-순)
4. [개선 효과 예측 요약](#4-개선-효과-예측-요약)

---

## 1. 현재 AI 평가 지표 해석

현재 `ml_engine/evaluator.py`의 평가 구조를 먼저 이해해야 합니다.

```
평가 방식: Proxy Label
  정답 레이블 = 임계치 초과(sensor_danger / sensor_caution) 알람
  TP = AI 알람 발생 후 X분 내 임계치 알람 발생
  FP = AI 알람 발생 후 X분 내 임계치 알람 없음
  FN = 임계치 알람 발생 전 X분 내 AI 알람 없음

매칭 창 (evaluator.py:54-55):
  FAST 탐지기 (Z-score, Change Point, IF, 상관관계): 10분
  SLOW 탐지기 (CUSUM, ARIMA):                       30분
```

**이 평가 방식의 본질적 한계**: 임계치 알람이 없으면 TP도 없습니다. AI가 임계치 이전에 조기 탐지하는 것이 목적인데, 임계치를 한 번도 안 넘으면 모든 AI 알람이 FP로 집계됩니다. 이 구조는 "진짜 조기 탐지 = FP로 분류"하는 역설을 안고 있습니다. 현재 이 구조를 전제로 개선 방향을 제안합니다.

---

## 2. 문제점 진단 (코드 레벨)

### 문제 1 — 앙상블이 탐지기 점수를 버린다

**파일**: `ml_engine/pipeline.py:100~126`  
**파일**: `ml_engine/isolation_forest.py:150`

```python
# pipeline.py:103-108
fired = []
if if_result["detected"]:      fired.append("isolation_forest")
if zscore_result["detected"]:  fired.append("zscore")
if cp_result["detected"]:      fired.append("changepoint")
if cusum_result["detected"]:   fired.append("cusum")

detector_count = len(fired)

# pipeline.py:117
if detector_count >= 2:
    current_status = "ML_ANOMALY"
```

Isolation Forest는 연속형 이상 점수(`score_samples()`)를 반환합니다:
```python
# isolation_forest.py:150
score = float(model.score_samples(x)[0])
```

점수가 `-0.6`(강한 이상)이든 `-0.02`(경계선)이든 `detected=True`가 되면 똑같이 1표입니다. 즉, **탐지기가 가진 확신도(confidence) 정보를 앙상블이 전혀 활용하지 않습니다.**

현재 구조로는:
- IF score = -0.01 (겨우 이상) + Z-score 발화 → ML_ANOMALY (과대 평가)
- IF score = -0.8 (강한 이상) 단독 → ML_ANOMALY (적절)
- IF score = -0.8 단독, Z-score 발화 안 함 → ML_ANOMALY (동일 결과지만 단독이므로 위 케이스와 같은 등급)

---

### 문제 2 — Isolation Forest contamination이 자동 튜닝되지 않는다

**파일**: `ml_engine/isolation_forest.py:33`  
**파일**: `ml_engine/evaluator.py:239-252`

```python
# isolation_forest.py:33
CONTAMINATION = 0.03    # 이상 비율 — 실측 데이터 기반 (임계치 알람/전체 2.6%)
```

```python
# evaluator.py:239-252
def _contamination_hint(fp_rate, recall) -> tuple:
    if fp_rate > 0.5:
        return 'lower', '오탐률 XX% — contamination을 낮추면 오탐 감소'
    if fp_rate < 0.1:
        return 'raise', '오탐률 XX% — contamination을 높이면 미탐지 감소'
    return 'ok', '오탐률 XX% — 현재 contamination 적정 수준'
```

`evaluator.py`가 힌트("낮추세요")를 화면에 표시하지만, **이 결과가 `isolation_forest.py`의 CONTAMINATION 값에 실제로 반영되지 않습니다.** 즉, 평가와 모델이 단절되어 있습니다.

---

### 문제 3 — ARIMA가 오염된 데이터로 학습한다

**파일**: `ml_engine/arima_forecaster.py:35-45`  
비교: `ml_engine/isolation_forest.py:54-68`

```python
# arima_forecaster.py:35-45 — 데이터 정제 없음
def _fit_arima(values: list[float]):
    arr = np.array(values, dtype=float)   # ← raw values 그대로
    fitted = ARIMA(arr, order=(1, 1, 1)).fit()
    return fitted
```

IF는 `_filter_normal_values()`로 danger 초과 값을 제거한 뒤 학습합니다:
```python
# isolation_forest.py:54-68
def _filter_normal_values(metric: str, values: list[float]) -> list[float]:
    """danger 임계치 이상인 값을 제거하여 정상 baseline 만 반환."""
    danger = t['danger']
    return [v for v in values if v < danger]
```

ARIMA에는 이 정제 단계가 없습니다. 윈도우(60개) 안에 이상값이 섞이면 ARIMA가 그 이상값을 "정상 추세"로 학습해서 예측선이 이상값 방향으로 뻗어나가고, 결과적으로 PREDICTIVE_ALERT가 실제 위험 직전이 아닌 **이상값이 섞인 직후**에 발화합니다.

---

### 문제 4 — CUSUM 파라미터가 가스 종류를 구분하지 않는다

**파일**: `ml_engine/cusum_detector.py:34-37`

```python
BASELINE_POINTS   = 20
REBASELINE_TICKS  = 500
K_SIGMA = 0.5       # 모든 가스·전력 동일
H_SIGMA = 4.0       # 모든 가스·전력 동일
```

이 파라미터는 "1σ 드리프트를 평균 8.5틱에 탐지"하는 설계이지만, 각 가스의 임계치와 측정 단위가 모두 다릅니다:

| 가스 | caution | danger | 정상 측정 범위 예시 | 비고 |
|------|---------|--------|-------------------|------|
| H2S  | 10 ppm  | 50 ppm | 0.1 ~ 5 ppm       | 소량에도 즉각 위험 |
| CO2  | 1000 ppm | 5000 ppm | 400 ~ 800 ppm   | 천천히 축적 |
| O3   | 0.05 ppm | 0.1 ppm | 0.01 ~ 0.03 ppm  | 절대값이 매우 작음 |

H_SIGMA=4.0이 만드는 알람 임계(`h = 4.0 × σ`)는 절대 단위에서 가스마다 전혀 다른 의미입니다. **빠르게 위험해지는 가스(H2S)는 H_SIGMA를 낮춰 민감하게, 완만하게 누적되는 가스(CO2)는 높여 FP를 줄여야 합니다.**

추가로, 절대값 게이트 비율도 고정입니다:
```python
# cusum_detector.py:43
_GATE_RATIO = 0.6   # caution × 0.6 미만이면 알람 억제
```

O3의 caution×0.6 = 0.03 ppm인데, 이 구간에서도 실제로는 드리프트가 의미있을 수 있습니다.

---

### 문제 5 — ARIMA 차수가 (1,1,1)로 고정되어 있다

**파일**: `ml_engine/arima_forecaster.py:42`

```python
fitted = ARIMA(arr, order=(1, 1, 1)).fit()
```

ARIMA(p, d, q)의 최적 차수는 데이터마다 다릅니다:
- 가스 센서는 주로 랜덤워크(d=1)이지만, AR(p)와 MA(q) 차수는 자기상관 구조에 따라 다름
- 전력 센서는 주기적 패턴이 있어 d=0이 더 적합할 수 있음
- (1,1,1)이 최적이 아닐 경우 예측 잔차가 커지고 PREDICTIVE_ALERT 타이밍이 부정확해짐

현재는 학습 실패 시 None 반환(safe fallback)이므로 차수 탐색을 추가해도 안전합니다.

---

### 문제 6 — anomaly_detector.py가 ML 슬라이딩 윈도우와 단절되어 있다

**파일**: `geofence/anomaly_detector.py:40-75`

```python
def get_recent_residual(device, gas_type: str) -> float:
    # DB에서 직접 최근 5분 평균, 직전 30분 평균을 쿼리
    recent_avg = SensorData.objects.filter(...).aggregate(avg=Avg(field))['avg']
    baseline_avg = SensorData.objects.filter(...).aggregate(avg=Avg(field))['avg']
    return float(recent_avg - baseline_avg)
```

이 함수는 **Zone tier 승격 판단용**(`zone_lifecycle.py:check_tier_upgrade`)입니다. 그런데 이미 `ml_engine/sliding_window.py`에 최신 60개 값이 Redis에 있고, `ml_engine/detectors.py`의 Z-score / Change Point 결과도 있습니다. anomaly_detector는 이것들을 전혀 쓰지 않고 **DB를 별도로 2번 쿼리**합니다.

zone tier 승격 시마다 DB 쿼리 2회 × 이웃 센서 수 → 불필요한 I/O입니다.

---

### 문제 7 — 탐지기별 성능이 분리 측정되지 않는다

**파일**: `ml_engine/evaluator.py:127-236`

```python
# evaluator.py:134
ml_qs = Alarm.objects.filter(alarm_type__in=_ML_TYPES, created_at__gte=cutoff)
# ... 전체 ML 알람을 하나로 묶어서 precision/recall 계산
```

현재 Precision/Recall은 **모든 AI 알람 타입을 합산**합니다. 즉 `ai_ml_anomaly`, `ai_drift_alert`, `ai_anomaly_warning` 등이 전부 섞여 집계됩니다.

결과: "AI 전체 Precision = 65%" — 이 숫자만으로는 어떤 탐지기를 개선해야 하는지 알 수 없습니다. `ai_drift_alert`의 Precision이 30%이고 `ai_ml_anomaly`가 85%일 수 있는데, 합산하면 둘 다 65% 근처로 묻힙니다.

실제로 `devices/views.py:71`에는 이런 주석이 있습니다:
```python
# "91.8%의 drift 알람이 escalation으로 300s 쿨다운을 우회하고 있었음"
```

이처럼 CUSUM drift는 FP가 많다는 것을 알고 있지만, **평가 화면에서 확인할 방법이 없습니다.**

---

### 문제 8 — Isolation Forest 특징 벡터에 방향성(기울기)이 없다

**파일**: `ml_engine/isolation_forest.py:71-86`

```python
def _make_features(baseline, current, last_actual=None):
    mu    = mean(baseline)
    sigma = stdev(baseline)
    prev  = last_actual if last_actual is not None else baseline[-1]
    diff  = current - prev           # 1차 차분 (변화량)
    ratio = current / (mu + EPS)
    return np.array([[current, mu, sigma, diff, ratio]])  # 5차원
```

현재 벡터: `[현재값, 평균, 표준편차, 1차변화량, 비율]`

`diff`는 직전 1틱과의 차이(1차 도함수)를 나타냅니다. 하지만 **2차 차분(가속도)** 또는 **최근 N틱의 추세 기울기(slope)**가 없습니다. 예를 들어:

- 상황 A: CO가 20, 21, 22, 23, 24 ppm으로 **꾸준히 상승 중** (기울기 = +1)
- 상황 B: CO가 22, 21, 24, 20, 24 ppm으로 **요동치는 중** (기울기 ≈ 0)

두 상황에서 마지막 값 24는 동일하고 diff도 비슷하지만, 상황 A가 훨씬 더 위험한 패턴입니다. 현재 IF 모델은 이 차이를 구분하기 어렵습니다.

---

### 문제 9 — CUSUM baseline 재산출 조건이 너무 보수적이다

**파일**: `ml_engine/cusum_detector.py:131-147`

```python
# cusum_detector.py:131-147
if st["tick"] % REBASELINE_TICKS == 0 and len(rb) >= BASELINE_POINTS:
    new_mu = mean(rb)
    new_sigma = stdev(rb)
    # 가스 환경이 실제로 변했을 때만 재산출 (5% 이상 변화)
    if abs(new_mu - st["mu"]) / (st["mu"] + EPS) > 0.05:
        st["mu"]     = new_mu
        ...
```

재산출 조건:
1. 500틱마다 (`REBASELINE_TICKS=500`)
2. 그 중에서도 평균 변화가 5% 초과일 때만

REBASELINE_TICKS=500에서 틱=1초이면 약 8분마다 재산출 시도입니다. 하지만 현장 가스 환경이 **공정 변화, 계절, 환기량**에 따라 몇 분 내에 바뀔 수 있는데, 5% 미만 변화라면 오래된 baseline이 계속 사용됩니다.

예: 기존 baseline CO_μ = 10 ppm. 새로운 공정 시작 후 정상 CO = 12 ppm (+20%). → 재산출됨  
예: 환기 상태 변화로 정상 CO = 10.4 ppm (+4%). → 재산출 안 됨 → S_high가 조금씩 누적 → 결국 FP 발화

---

### 문제 10 — AIPrediction 검증 결과가 피드백 루프로 연결되지 않는다

**파일**: `devices/views.py:470-501` (검증)  
**파일**: `ml_engine/arima_forecaster.py` (학습)

```python
# devices/views.py:490-501
if actual_value >= pred.threshold:
    success_ids.append(pred.id)   # DB 업데이트만
elif now >= pred.expires_at:
    failure_ids.append(pred.id)   # DB 업데이트만
```

AIPrediction의 `result='success'/'failure'`가 DB에 쌓이지만, 이 정보는:
- `evaluator.py`에서 통계 수집 (표시용)에만 사용됨
- ARIMA 모델 재학습 트리거나 예측 창(FORECAST_STEPS) 조정에 사용되지 않음

즉, **ARIMA가 지속적으로 틀려도 모델이 자동으로 개선되지 않습니다.**

---

## 3. 개선 방안 (우선순위 순)

> 우선순위 기준: **구현 난이도 대비 신뢰성 향상 효과**

---

### 🥇 [우선순위 1] ARIMA 학습 데이터 정제

**효과**: 예측 타이밍 정확도 향상 / 구현 난이도: 낮음 (코드 5줄)  
**파일**: `ml_engine/arima_forecaster.py:35-45`

**현재 코드**:
```python
def _fit_arima(values: list[float]):
    arr = np.array(values, dtype=float)   # raw 그대로
    fitted = ARIMA(arr, order=(1, 1, 1)).fit()
    return fitted
```

**개선 방향**:
```python
def _fit_arima(values: list[float], metric: str = '', device_id: str = ''):
    # IF와 동일한 정제 로직 재사용
    if metric:
        from ml_engine.isolation_forest import _filter_normal_values
        clean = _filter_normal_values(metric, values)
        # 정제 후 MIN_POINTS 이상이면 정제값 사용, 아니면 raw fallback
        train = clean if len(clean) >= MIN_POINTS else values
    else:
        train = values

    arr = np.array(train, dtype=float)
    fitted = ARIMA(arr, order=(1, 1, 1)).fit()
    return fitted
```

`forecast()` 호출부(`pipeline.py:92`)에서 `metric`이 이미 전달되고 있으므로, `_fit_arima`에 그대로 넘기면 됩니다.

**근거**: IF가 이미 `_filter_normal_values()`로 같은 문제를 해결했습니다. ARIMA도 동일 함수를 재사용하면 됩니다. 코드 5줄 변경으로 이상값이 예측선을 왜곡하는 문제가 해결됩니다.

---

### 🥇 [우선순위 1] Isolation Forest — 점수 기반 신뢰도 활용

**효과**: 앙상블 과민 반응 감소 + FP 감소 / 구현 난이도: 낮음  
**파일**: `ml_engine/pipeline.py:100-126`

**현재 코드의 문제**:
```python
if if_result["detected"]:      fired.append("isolation_forest")  # 점수 무시
```

**개선 방향**: IF score를 그대로 반환하고 있으므로 임계를 분리합니다.

```python
# isolation_forest.py에서 신뢰도 등급 추가
_SCORE_HIGH_CONF = -0.15   # 강한 이상 (model.score_samples 기준 음수일수록 이상)
_SCORE_LOW_CONF  = -0.05   # 경계선 이상

# pipeline.py 앙상블 부분 개선
if_detected = if_result["detected"]
if_score    = if_result.get("score", 0.0)
if_high_conf = if_detected and if_score < _SCORE_HIGH_CONF  # 강한 이상

fired = []
if if_detected:      fired.append("isolation_forest")
if zscore_result["detected"]:  fired.append("zscore")
if cp_result["detected"]:      fired.append("changepoint")
if cusum_result["detected"]:   fired.append("cusum")

detector_count = len(fired)

# 기존: detector_count >= 2 → ML_ANOMALY
# 개선: IF 단독이어도 점수가 강하면 ML_ANOMALY, 약하면 ANOMALY_WARNING으로 강등
if detector_count >= 2:
    current_status = "ML_ANOMALY"
elif if_high_conf:                    # IF 단독 + 강한 이상
    current_status = "ML_ANOMALY"
elif if_detected and not if_high_conf: # IF 단독 + 약한 이상
    current_status = "ANOMALY_WARNING"  # 한 단계 낮게
elif zscore_result["detected"]:
    current_status = "ANOMALY_WARNING"
elif cp_result["detected"]:
    current_status = "TREND_SHIFT"
else:
    current_status = "NORMAL"
```

**근거**: 현재 IF 단독 발화 = ML_ANOMALY인데, score=-0.01 수준의 경계선 이상이 ML_ANOMALY가 되는 건 과민합니다. IF가 이미 score를 계산하고 있음에도 binary로만 사용하고 있어 정보 손실이 있습니다.

---

### 🥇 [우선순위 1] 탐지기별 성능 분리 집계

**효과**: 어떤 탐지기를 튜닝해야 하는지 즉시 파악 / 구현 난이도: 낮음  
**파일**: `ml_engine/evaluator.py:127-236`

**현재 코드**:
```python
ml_qs = Alarm.objects.filter(alarm_type__in=_ML_TYPES, ...)
# ... 하나로 합산
```

**개선 방향**:
```python
# 탐지기 타입별 그룹핑
_DETECTOR_GROUPS = {
    'isolation_forest': {'ai_ml_anomaly'},
    'zscore':           {'ai_anomaly_warning'},
    'changepoint':      {'ai_trend_shift'},
    'cusum':            {'ai_drift_alert'},
    'arima':            {'ai_predictive_alert', 'ai_predictive_warning'},
    'correlation':      {'ai_correlation'},
}

# 각 그룹별로 동일한 TP/FP 계산 반복
per_detector = {}
for detector_name, types in _DETECTOR_GROUPS.items():
    d_ml = ml_qs.filter(alarm_type__in=types)
    d_tp = d_ml.filter(Exists(th_after_fast)).count()  # FAST/SLOW 분류 유지
    d_total = d_ml.count()
    per_detector[detector_name] = {
        'total':     d_total,
        'tp':        d_tp,
        'fp':        d_total - d_tp,
        'precision': round(d_tp / d_total * 100, 1) if d_total > 0 else None,
    }
```

결과를 `return` dict에 `'per_detector': per_detector`로 추가하고 AI 메트릭 화면에 표를 하나 더 추가하면, "CUSUM Precision = 24%, IF Precision = 71%" 같은 구체적 수치가 나옵니다.

---

### 🥈 [우선순위 2] Contamination 자동 피드백 루프

**효과**: IF 모델이 운영 데이터에 맞게 자동 수렴 / 구현 난이도: 중간  
**파일**: `ml_engine/isolation_forest.py:33`, `ml_engine/evaluator.py:239`

현재는 evaluator가 힌트만 줍니다. 이것을 자동 적용하는 방식으로 변경합니다.

**개선 방향**:
```python
# isolation_forest.py 상단에 동적 contamination 관리 추가
_contamination_overrides: dict = {}  # metric → float

def set_contamination(metric: str, value: float) -> None:
    """evaluator.py 가 fp_rate 기반으로 주기적으로 호출."""
    clamped = max(0.005, min(0.10, value))  # 0.5% ~ 10% 범위 제한
    _contamination_overrides[metric] = clamped
    # 다음 재학습 주기에 새 contamination 적용되도록 모델 캐시 무효화
    keys_to_invalidate = [k for k in _models if k.endswith(f":{metric}")]
    with _lock:
        for k in keys_to_invalidate:
            _models.pop(k, None)

def _get_contamination(metric: str) -> float:
    return _contamination_overrides.get(metric, CONTAMINATION)
```

```python
# evaluator.py의 _contamination_hint를 실제 조정으로 확장
def apply_contamination_hint(fp_rate, recall, metric: str) -> None:
    if fp_rate is None:
        return
    current = _get_contamination(metric)
    if fp_rate > 0.5:   # 오탐 너무 많음 → 낮추기
        new_c = current * 0.8
    elif fp_rate < 0.1 and recall is not None and recall < 0.5:  # 미탐 많음 → 높이기
        new_c = current * 1.2
    else:
        return
    set_contamination(metric, new_c)
```

**중요 제약**: contamination 변경은 **모델 재학습 주기(50틱)**에 맞춰 자연스럽게 반영됩니다. 즉각 반영이 아니므로 운영 중 급격한 변화는 없습니다.

---

### 🥈 [우선순위 2] CUSUM — 가스별 H_SIGMA 분리

**효과**: 빠른 가스의 누락 탐지(FN) 감소 + 느린 가스의 FP 감소 / 구현 난이도: 중간  
**파일**: `ml_engine/cusum_detector.py:36-37`

**현재 코드**:
```python
K_SIGMA = 0.5   # 모든 가스 동일
H_SIGMA = 4.0   # 모든 가스 동일
```

**개선 방향**:
```python
# 가스별 H_SIGMA — 위험 속도에 반비례
# 빠른 위험(H2S, CO): 낮게 → 민감하게 탐지
# 느린 축적(CO2, VOC): 높게 → FP 감소
_METRIC_H_SIGMA = {
    'h2s':  3.0,   # IDLH 50ppm, 빠른 위험 → 민감하게
    'co':   3.5,   # IDLH 200ppm, 비교적 빠름
    'no2':  3.5,
    'so2':  3.5,
    'o3':   3.0,   # 낮은 절대 임계치, 민감해야
    'nh3':  3.5,
    'co2':  5.0,   # 천천히 축적, FP 방지
    'voc':  4.5,
    'o2':   3.0,   # 저산소/고산소 모두 빠른 위험
    # 전력: 기본값 유지
}
_DEFAULT_H_SIGMA = 4.0

def _get_h_sigma(metric: str) -> float:
    return _METRIC_H_SIGMA.get(metric, _DEFAULT_H_SIGMA)
```

`detect_drift()` 내부에서 `h = H_SIGMA * sigma` 부분을 `h = _get_h_sigma(metric) * sigma`로 교체합니다. `metric`은 이미 `detect_drift(device_id, metric, value, ...)`로 전달받고 있습니다.

---

### 🥈 [우선순위 2] anomaly_detector.py — ML 슬라이딩 윈도우 연동

**효과**: DB 쿼리 제거 + Zone tier 승격 판정 정확도 향상 / 구현 난이도: 중간  
**파일**: `geofence/anomaly_detector.py:40-75`

**현재**: DB에서 직접 5분/30분 평균을 계산  
**개선**: ml_engine 슬라이딩 윈도우 + Z-score 결과 재사용

```python
# geofence/anomaly_detector.py 개선안
from ml_engine.sliding_window import get_values
from ml_engine.detectors import detect_zscore, detect_changepoint

def has_anomaly(device, gas_type: str, threshold: float = None) -> bool:
    """
    ML 슬라이딩 윈도우 기반 이상 판정.
    Redis 캐시 사용 → DB 쿼리 없음.
    """
    values = get_values(device.device_id, gas_type)
    if len(values) < 10:
        # 데이터 부족 → 기존 DB 방식 fallback
        return _legacy_has_anomaly(device, gas_type, threshold)

    current = values[-1]
    zscore = detect_zscore(values, current)
    cp = detect_changepoint(values)

    # Z-score 또는 Change Point 중 하나라도 감지되면 이상
    return zscore["detected"] or cp["detected"]

def _legacy_has_anomaly(device, gas_type, threshold):
    """기존 DB 방식 (데이터 부족 fallback)"""
    # ... 기존 코드 유지
```

---

### 🥉 [우선순위 3] Isolation Forest 특징 벡터 — 기울기(slope) 추가

**효과**: 완만한 상승 추세 초기 탐지 / 구현 난이도: 낮음 (벡터 1차원 추가)  
**파일**: `ml_engine/isolation_forest.py:71-101`

**현재 5차원**: `[value, roll_mean, roll_std, diff, ratio]`

**개선 6차원**: `[value, roll_mean, roll_std, diff, ratio, slope]`

```python
def _make_features(baseline, current, last_actual=None):
    mu    = mean(baseline) if baseline else current
    sigma = stdev(baseline) if len(baseline) >= 2 else 0.0
    prev  = last_actual if last_actual is not None else (baseline[-1] if baseline else current)
    diff  = current - prev
    ratio = current / (mu + EPS)

    # slope: 최근 5개 값의 선형 기울기 (단순 (last - first) / n)
    n_slope = min(5, len(baseline))
    if n_slope >= 2:
        slope = (baseline[-1] - baseline[-n_slope]) / (n_slope - 1)
    else:
        slope = 0.0

    return np.array([[current, mu, sigma, diff, ratio, slope]], dtype=float)
```

`_make_feature_matrix`도 동일하게 `slope` 열을 추가합니다. **기존 모델과 차원이 달라지므로 재학습 필요** — `_models` 캐시를 서버 재시작 시 초기화하거나, `model_store.py`의 pkl 파일을 삭제하면 됩니다.

---

### 🥉 [우선순위 3] ARIMA 차수 자동 선택

**효과**: 가스/전력별 최적 예측 모델 / 구현 난이도: 높음  
**파일**: `ml_engine/arima_forecaster.py:35-45`

현재 `ARIMA(arr, order=(1,1,1))` 고정 → `pmdarima` 라이브러리의 `auto_arima`로 교체합니다.

```python
# requirements.txt에 pmdarima 추가 필요
def _fit_arima(values: list[float], metric: str = ''):
    clean = _filter_normal_values(metric, values) if metric else values
    train = clean if len(clean) >= MIN_POINTS else values
    arr = np.array(train, dtype=float)

    try:
        import pmdarima as pm
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = pm.auto_arima(
                arr,
                start_p=0, max_p=2,
                start_q=0, max_q=2,
                d=None,             # ADF 검정으로 자동 결정
                information_criterion='aic',
                stepwise=True,      # 전체 탐색 대신 stepwise (빠름)
                error_action='ignore',
                suppress_warnings=True,
            )
            return model
    except Exception:
        # pmdarima 실패 시 기존 방식 fallback
        return ARIMA(arr, order=(1, 1, 1)).fit()
```

단, `auto_arima`는 기존 ARIMA보다 학습이 2~5배 느립니다. **백그라운드 학습(세마포어 2개 제한)** 구조이므로 실시간 성능에 영향은 없으나, 모델 준비까지 시간이 길어집니다.

---

### 🥉 [우선순위 3] CUSUM baseline 재산출 조건 완화

**효과**: 환경 변화 빠른 적응 (FP 감소) / 구현 난이도: 낮음  
**파일**: `ml_engine/cusum_detector.py:131-147`

**현재**: 500틱마다 + 5% 초과 변화 시에만  
**개선**: 변화 임계를 3%로 낮추거나 조건을 분리

```python
# cusum_detector.py:139 — 현재
if abs(new_mu - st["mu"]) / (st["mu"] + EPS) > 0.05:   # 5%

# 개선: 메트릭별 민감도 차등
_REBASELINE_CHANGE_TH = {
    'h2s': 0.03,   # 민감 가스: 3%만 변해도 재산출
    'co':  0.03,
    'co2': 0.08,   # 완만 가스: 8% 이상 변화 시에만
    'default': 0.05,
}

change_th = _REBASELINE_CHANGE_TH.get(metric, _REBASELINE_CHANGE_TH['default'])
if abs(new_mu - st["mu"]) / (st["mu"] + EPS) > change_th:
    ...
```

---

## 4. 개선 효과 예측 요약

| 우선순위 | 개선 항목 | 영향 지표 | 예상 효과 | 수정 파일 | 난이도 |
|---------|---------|---------|---------|---------|-------|
| 🥇 | ARIMA 학습 데이터 정제 | ARIMA 예측 타이밍 정확도 | PREDICTIVE_ALERT FP ↓ | `arima_forecaster.py` | 낮음 |
| 🥇 | IF 점수 기반 신뢰도 | `ai_ml_anomaly` FP ↓ | 경계선 이상을 ANOMALY_WARNING으로 강등 | `pipeline.py` | 낮음 |
| 🥇 | 탐지기별 성능 분리 집계 | 평가 신뢰성 | 어떤 탐지기가 문제인지 즉시 파악 가능 | `evaluator.py` | 낮음 |
| 🥈 | Contamination 자동 튜닝 | IF precision/recall 균형 | 운영 데이터에 맞게 자동 수렴 | `isolation_forest.py`, `evaluator.py` | 중간 |
| 🥈 | CUSUM H_SIGMA 가스별 분리 | `ai_drift_alert` FP ↓ / FN ↓ | H2S 미탐지 감소, CO2 FP 감소 | `cusum_detector.py` | 중간 |
| 🥈 | anomaly_detector ML 연동 | Zone 승격 정확도 + DB I/O | ML 결과 재사용, 별도 DB 쿼리 제거 | `anomaly_detector.py` | 중간 |
| 🥉 | IF 특징 벡터 slope 추가 | 완만한 상승 탐지율(Recall) ↑ | 추세 상승 초기 탐지 | `isolation_forest.py` | 낮음* |
| 🥉 | ARIMA 차수 자동 선택 | ARIMA 예측 정확도 | 가스/전력별 최적 모델 | `arima_forecaster.py` | 높음 |
| 🥉 | CUSUM 재산출 조건 완화 | drift FP ↓ | 환경 변화 빠른 적응 | `cusum_detector.py` | 낮음 |

\* 기존 pkl 모델 파일 삭제(재학습) 필요

---

## 핵심 정리

현재 AI 시스템의 가장 큰 구조적 문제는 **"탐지 → 평가 → 개선"의 피드백 루프가 끊겨 있다**는 것입니다.

```
현재:
  탐지 → (알람 생성) → 평가 (수동 확인)
                           ↑ 끊김
  모델 (고정 파라미터)

개선 목표:
  탐지 → (알람 생성) → 평가 → contamination 자동 조정
                                    ↓
  모델 ← (재학습 주기에 반영) ←────┘
```

**우선순위 1 세 가지**(ARIMA 데이터 정제, IF 점수 기반 신뢰도, 탐지기별 성능 분리)는 코드 변경량이 적고 즉각적인 효과가 있습니다. 특히 **탐지기별 성능 분리**는 나머지 모든 개선의 전제 조건입니다 — "어떤 탐지기가 문제인지" 수치로 보여야 다음 튜닝 방향이 결정되기 때문입니다.

---

*분석일: 2026-05-21*  
*분석 대상: `ml_engine/`, `devices/views.py`, `alerts/`, `geofence/anomaly_detector.py`*
