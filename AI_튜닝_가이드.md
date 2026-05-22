# SenSa AI 파이프라인 튜닝 가이드

---

## 1. 수정 가능한 AI 성능 튜닝 변수

### 1-1. CUSUM `ml_engine/cusum_detector.py`

| 변수 | 현재값 | 역할 | 올리면 | 내리면 |
|---|---|---|---|---|
| `H_SIGMA` | `4.0` | 알람 발화 임계 (누적합 기준) | 더 큰 드리프트만 탐지 → FP ↓, 탐지 지연 ↑ | 민감도 ↑, FP ↑ |
| `K_SIGMA` | `0.5` | 자연 변동 허용폭 | 작은 진동 무시 → FP ↓ | 민감도 ↑ |
| `_GATE_RATIO` | `0.6` | 안전 구간 기준 (caution×비율 미만이면 억제) | 게이트 좁아져 더 일찍 알람 | 안전 구간 넓어져 FP ↓ |
| `_O2_GATE_MARGIN` | `0.1` | O2 안전 구간 마진 (caution×1.1 초과면 억제) | 억제 구간 좁아짐 | 억제 구간 넓어짐 |
| `BASELINE_POINTS` | `20` | baseline μ/σ 산출 포인트 수 | 안정적인 baseline | 빠른 초기화 |
| `REBASELINE_TICKS` | `500` | baseline 재산출 주기 (틱) | 환경 변화 반응 느림 | 잦은 재산출 |

---

### 1-2. IsolationForest `ml_engine/isolation_forest.py`

| 변수 | 현재값 | 역할 | 올리면 | 내리면 |
|---|---|---|---|---|
| `CONTAMINATION` | `0.03` | 전체 데이터 중 이상치 비율 가정 | 더 많이 이상으로 분류 → FP ↑ | 더 보수적 탐지 → FP ↓ |
| `MIN_TRAIN` | `30` | 학습 시작 최소 포인트 수 | 충분한 데이터 후 탐지 | 빠른 탐지 시작 (불안정) |
| `RETRAIN_INTERVAL` | `50` | N 포인트마다 재학습 | 환경 적응 느림 | 잦은 재학습 (CPU 부하) |

---

### 1-3. Z-score / ChangePoint `ml_engine/detectors.py`

| 변수 | 현재값 | 역할 | 올리면 | 내리면 |
|---|---|---|---|---|
| `ZSCORE_THRESHOLD` | `3.0` | Z-score 이상 기준 (`\|z\| > 값` 이면 발화) | 급격한 이상만 탐지 → FP ↓ | 민감도 ↑ |
| `MEAN_SHIFT_THRESHOLD` | `2.5` | ChangePoint 평균 이동 기준 | FP ↓ | 민감도 ↑ |
| `STD_RATIO_THRESHOLD` | `2.5` | ChangePoint 분산 변화 기준 | FP ↓ | 민감도 ↑ |
| `WINDOW_HALF` | `20` | ChangePoint 비교 구간 크기 (최소 40개 필요) | 더 긴 추세 비교 | 빠른 반응 |

---

### 1-4. ARIMA `ml_engine/arima_forecaster.py`

| 변수 | 현재값 | 역할 | 올리면 | 내리면 |
|---|---|---|---|---|
| `MIN_POINTS` | `30` | 학습 시작 최소 포인트 수 | 충분한 데이터 후 예측 | 빠른 예측 시작 (불안정) |
| `FORECAST_STEPS` | `10` | 몇 틱 앞을 예측할지 (1틱≈1초) | 더 먼 미래 예측 → 오차 ↑ | 짧은 예측 → 정확도 ↑ |
| `RETRAIN_INTERVAL` | `50` | N 포인트마다 재학습 | 환경 적응 느림 | CPU 부하 ↑ |

---

### 1-5. 알람 쿨다운 / 에스컬레이션 `devices/views.py`

| 변수 | 현재값 | 역할 | 올리면 | 내리면 |
|---|---|---|---|---|
| `_GAS_COOLDOWN_SEC` | `300` | 가스 AI 알람 재발화 억제 시간 (초) | 중복 알람 ↓ → Precision ↑ | 빠른 재탐지 |
| `_BASE_COOLDOWN_SEC` | `60` | 기본 쿨다운 (전력·에스컬레이션) | 중복 ↓ | 빠른 재탐지 |
| `ESCALATION_THRESHOLD` | `3` | N회 반복 발화 시 레벨 상향 | 더 많은 반복 필요 | 빠른 에스컬레이션 |
| `ESCALATION_WINDOW_SEC` | `300` | 에스컬레이션 집계 윈도우 (초) | 더 긴 관찰 후 에스컬레이션 | 빠른 에스컬레이션 |

---

### 1-6. 위험 임박 쿨다운 우선 통과 `devices/views.py`

쿨다운 중이어도 아래 조건을 모두 만족하면 즉시 알람 발화.

| 변수 | 현재값 | 역할 |
|---|---|---|
| `_BYPASS_DETECTOR_MIN` | `3` | 탐지기 N개 이상 동시 발화 시 쿨다운 무시 |
| `_BYPASS_VALUE_RATIO` | `2.0` | 직전 알람 이후 농도 N배 급등 시 쿨다운 무시 |
| `_BYPASS_DANGER_RATIO` | `0.8` | 위험 임계치의 80% 이상 도달 시 쿨다운 무시 |

---

### 지금 당장 Precision 향상에 효과적인 변수 우선순위

```
1순위: _GAS_COOLDOWN_SEC  (300 → 600)
       같은 센서에서 10분 내 AI 알람 반복 억제 → Precision 직접 상승

2순위: CONTAMINATION  (0.03 → 0.02)
       IF가 더 보수적으로 이상 판정 → FP ↓

3순위: _GATE_RATIO  (0.6 → 0.5)
       CUSUM 안전 구간 더 넓게 → 억제 범위 확대
```

---

## 2. AI 위험 예측 원리 및 계산식

### 전체 구조

```
센서 값 1개 입력
│
├─ 현재 위험 판단 (즉각 탐지)
│   ├─ Z-score         → ANOMALY_WARNING
│   ├─ ChangePoint     → TREND_SHIFT
│   ├─ IsolationForest → ML_ANOMALY
│   └─ CUSUM           → 앙상블 참여만 (단독 알람 없음)
│       ↓
│   앙상블 투표 → 최종 current_status
│
└─ 미래 위험 예측 (독립 계산)
    └─ ARIMA → PREDICTIVE_ALERT / PREDICTIVE_WARNING
```

> ARIMA와 나머지 4개 탐지기는 모두 Redis 슬라이딩 윈도우의 **원시 센서 측정값**을 독립적으로 읽습니다. 서로의 결과를 공유하지 않습니다.

---

### 탐지기 1. Z-score — 단발 급등 탐지

**언제**: 측정값이 갑자기 크게 튀었을 때

**계산식**:
```
① MAD = median( |각 값 - 전체 중앙값| )
② σ_est = 1.4826 × MAD     (정규분포 기준 환산 계수, NIST 표준)
③ z = |현재값 - 중앙값| / σ_est

z > 3.0  →  ANOMALY_WARNING
```

**왜 평균/표준편차 대신 중앙값/MAD?**
이상값이 윈도우에 섞이면 평균이 끌려 올라가 z값이 오히려 작아지는 역설이 생깁니다.
중앙값은 이상값에 끌리지 않아 일관된 탐지가 가능합니다.

**예시 (CO, caution=25ppm)**:
```
최근 60개 값 중앙값: 8ppm, MAD: 1.2ppm
σ_est = 1.4826 × 1.2 = 1.78ppm
현재값: 14ppm
z = |14 - 8| / 1.78 = 3.37  →  3.0 초과 → 발화
```

---

### 탐지기 2. ChangePoint — 패턴 변화 탐지

**언제**: 값 자체는 정상 범위지만 최근 들어 분포가 달라졌을 때

**계산식**:
```
이전 20개 구간: mean_prev, std_prev
최근 20개 구간: mean_curr, std_curr

① std_combined = sqrt( (std_prev² + std_curr²) / 2 )
② mean_shift_score = |mean_curr - mean_prev| / std_combined
③ std_ratio = max(std_curr, std_prev) / min(std_curr, std_prev)

mean_shift_score > 2.5  →  TREND_SHIFT  (평균이 이동)
std_ratio > 2.5         →  TREND_SHIFT  (변동폭이 갑자기 커짐)
```

**예시 (CO)**:
```
이전 20개 평균: 5ppm, std: 0.8ppm
최근 20개 평균: 9ppm, std: 1.0ppm
std_combined = sqrt((0.64 + 1.0) / 2) = 0.91
mean_shift = |9 - 5| / 0.91 = 4.39  →  2.5 초과 → 발화
```

---

### 탐지기 3. IsolationForest — 복합 패턴 이상 탐지

**언제**: 단일 값이 아닌 여러 측면(값, 변화율, 비율)을 종합했을 때 이상한 경우

**입력 특징 벡터 (5차원)**:
```
[1] value      = 현재 측정값
[2] roll_mean  = 정상 데이터만 거른 평균   (danger 초과값 제외)
[3] roll_std   = 정상 데이터만 거른 표준편차
[4] diff       = 현재값 - 직전 측정값      (변화율)
[5] ratio      = 현재값 / roll_mean        (상대적 크기)
```

**작동 원리**:
```
정상 데이터로 IsolationForest 학습
  contamination = 0.03  (전체의 3%를 이상치로 가정)
  n_estimators  = 100   (의사결정트리 100개 앙상블)

현재 벡터를 숲에 통과
  prediction =  1  (정상)
  prediction = -1  (이상) → ML_ANOMALY

score: 음수에 가까울수록 이상 (보통 -0.3 이하가 이상 구간)
```

**준지도 학습 적용**:
학습 데이터에서 danger 임계치 이상인 값을 제거합니다.
누출 상황의 값을 "정상"으로 학습하는 개념 오염을 방지하기 위함입니다.

---

### 탐지기 4. CUSUM — 느린 드리프트 탐지

**언제**: 값이 서서히 한 방향으로 계속 올라갈 때
(각 포인트는 정상 범위라 Z-score가 못 잡는 경우)

**계산식**:
```
초기 20개 포인트로 기준값 산출:
  μ (기준 평균),  σ (기준 표준편차)

매 틱마다:
  k = 0.5 × σ           (자연 변동 허용폭)
  h = 4.0 × σ           (알람 발화 임계)

  S_high = max(0, S_high_이전 + (현재값 - μ - k))   ← 상향 누적합
  S_low  = max(0, S_low_이전  + (μ - k - 현재값))   ← 하향 누적합

S_high > h  →  상향 드리프트 탐지
S_low  > h  →  하향 드리프트 탐지
```

**절대값 게이트 (FP 감소 적용)**:
```
일반 가스: 현재값 < caution × 0.6  →  알람 억제 (S는 계속 누적)
O2:        현재값 > caution × 1.1  →  알람 억제 (S는 계속 누적)

S를 리셋하지 않으므로 값이 위험 구간에 진입하는 순간 즉시 발화.
```

**예시 (CO, caution=25ppm, 게이트=15ppm)**:
```
μ=5ppm, σ=1ppm → k=0.5, h=4.0

틱1:  CO=6.2ppm   S_high=0.7    값<15 → 알람 억제 (S 보존)
틱2:  CO=7.1ppm   S_high=1.3    억제
틱3:  CO=8.4ppm   S_high=3.2    억제
...
틱N:  CO=16.5ppm  S_high=6.8 > 4.0  &  값≥15 → 발화!
```

**단독 발화 정책**:
CUSUM이 단독으로 발화해도 알람을 생성하지 않습니다.
다른 탐지기와 동시에 발화(detector_count ≥ 2)할 때만 ML_ANOMALY로 처리됩니다.

---

### 탐지기 5. ARIMA — 미래값 예측

**언제**: 지금은 괜찮지만 추세를 보면 곧 위험해질 것 같을 때

**계산식**:
```
ARIMA(1, 1, 1) 모델:
  AR(1): 현재값 = φ × 직전값 + 잡음        (자기회귀)
  I(1):  1차 차분(differencing)             (추세 제거)
  MA(1): 잡음 = ε + θ × 직전잡음           (이동평균)

슬라이딩 윈도우 30~60개 포인트로 학습
→ 10틱(약 10초) 앞 예측값 목록 생성

예측값 중 최댓값 ≥ danger_threshold   →  PREDICTIVE_ALERT
예측값 중 최댓값 ≥ caution_threshold  →  PREDICTIVE_WARNING
```

**예시 (CO, caution=25ppm, danger=200ppm)**:
```
최근 데이터: [8, 9, 11, 13, 15, 17 ...] (계속 상승)
10틱 후 예측: [19, 21, 23, 25, 27 ...]
예측 최댓값 27 ≥ caution 25  →  PREDICTIVE_WARNING
```

**성능 최적화**:
- 매 틱마다 재학습하지 않고 `apply(new_data)`로 최신 데이터만 반영
- 50 포인트마다 백그라운드 스레드에서 재학습 (최대 동시 2개)
- 학습 중에는 이전 캐시 모델을 그대로 사용

---

## 3. 앙상블 투표로 최종 위험도 결정

```
발화 탐지기 수
  ≥ 2개    →  ML_ANOMALY        (danger 레벨)   여러 신호 동시 = 확실한 위험
  = IF만   →  ML_ANOMALY        (danger 레벨)   IF 단독은 신뢰도 높음
  = Z만    →  ANOMALY_WARNING   (caution 레벨)
  = CP만   →  TREND_SHIFT       (caution 레벨)
  = CUSUM만→  NORMAL            (알람 없음)     단독 발화 억제
  없음     →  NORMAL
```

ARIMA는 이 투표와 **별개로** 독립 실행됩니다.
`current_status=NORMAL` 이어도 `predictive_status=PREDICTIVE_WARNING` 이 동시에 나올 수 있습니다.

---

## 4. 알람 타입 매핑

| AI 상태 | alarm_type | 기본 레벨 |
|---|---|---|
| `ML_ANOMALY` | `ai_ml_anomaly` | danger |
| `ANOMALY_WARNING` | `ai_anomaly_warning` | caution |
| `TREND_SHIFT` | `ai_trend_shift` | caution |
| `DRIFT_ALERT` | `ai_drift_alert` | caution |
| `PREDICTIVE_ALERT` | `ai_predictive_alert` | caution |
| `PREDICTIVE_WARNING` | `ai_predictive_warning` | info |
| 다중 가스 동시 이상 | `ai_correlation` | caution |

---

## 5. 탐지기별 요약

| 탐지기 | 핵심 계산 | 탐지 대상 | 단독 알람 |
|---|---|---|---|
| Z-score | `z = \|값 - 중앙값\| / (1.4826 × MAD)` | 단발 급등 | O |
| ChangePoint | `mean_shift = \|평균차\| / std_합성` | 분포 이동 | O |
| IsolationForest | 5차원 벡터 → 숲 통과 → 이상 점수 | 복합 이상 | O |
| CUSUM | `S = max(0, S_이전 + 값변화 - 허용폭)` | 느린 드리프트 | X (앙상블만) |
| ARIMA | `ARIMA(1,1,1) → 10틱 후 예측` | 미래 임계치 초과 | O (별도 경로) |
