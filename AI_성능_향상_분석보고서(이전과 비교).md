# AI 브랜치 비교 분석 보고서
**`AI_test_shj` → `integrate/shj-teamwork`**  
작성일: 2026-05-28 (최초: 2026-05-22) | 작성자: Hojun Seo

---

## 📌 한눈에 보기

| 구분 | AI_test_shj (이전) | integrate/shj-teamwork (현재) |
|------|-------------------|-------------------------------|
| AI 탐지 엔진 | anomaly_detector + trend_predictor (2개 파일) | ml_engine 패키지 (8개 모듈) |
| 탐지기 수 | 2종 (ARIMA 잔차, IsolationForest) | **6종** (Z-score, ChangePoint, IF, ARIMA, CUSUM, 상관관계) |
| AI 알람 타입 | ai_prediction 단일 타입 | **7종** 세분화 |
| 앙상블 투표 | ❌ 없음 | ✅ 2개 이상 동시 발화 → ML_ANOMALY 에스컬레이션 |
| 데이터 윈도우 | 메모리 deque (최대 200~500개) | **Redis ZSET** (60개, 10분 TTL) |
| 성능 지표 자동 평가 | ❌ 없음 | ✅ Proxy Label (Precision/Recall/F1) |
| contamination 자동 조정 | ❌ 없음 | ✅ FP rate 기반 ±0.005 자동 튜닝 |
| 백오피스 AI 모니터링 화면 | ❌ 없음 | ✅ /backoffice/ai-metrics/ |
| state_store TTL | 5분 | **30분** (단기 통신 끊김 대응) |
| 알람 목록 그루핑 | 건별 나열 | **10분 이벤트 단위** 그루핑 |
| 의존성 추가 | - | statsmodels >= 0.14 |

---

## 1. 가장 큰 변화 — AI 엔진 전면 교체

### 이전 구조 (AI_test_shj)

```
sensors → devices/views.py
              ↓
    anomaly_detector.py      (ARIMA 잔차 기반 이상 탐지)
    trend_predictor.py       (IsolationForest + 선형회귀)
              ↓
    알람 타입: ai_prediction (단일)
```

**문제점**
- `anomaly_detector`: 윈도우가 이상값으로 채워지면 잔차가 0에 수렴 → 지속 이상 상태 탐지 불가
- `trend_predictor`: IsolationForest + 선형회귀만으로는 완만한 농도 상승(드리프트) 탐지 어려움
- 모든 AI 알람이 `ai_prediction` 단일 타입 → 어떤 방식으로 탐지했는지 구분 불가
- 탐지기가 서로 독립적 동작, 여러 탐지기가 동시에 반응해도 레벨 강화 없음
- 성능 측정 수단 없음

---

### 현재 구조 (AI_test_shj_2)

```
sensors → devices/views.py
    ├── 스레드 A: evaluate_sensor()   (임계치 기반 상태 전이)
    └── 스레드 B: ai_pipeline.analyze()
                    ↓
        ml_engine 패키지
          sliding_window (Redis)   ← 데이터 저장소
          detectors.py             ← Z-score + ChangePoint
          isolation_forest.py      ← IF (6차원 특징벡터)
          arima_forecaster.py      ← ARIMA(1,1,1) 예측
          cusum_detector.py        ← 드리프트 탐지 (신규)
          pipeline.py              ← 앙상블 투표 통합
          evaluator.py             ← 성능 자동 평가
              ↓
    7종 알람 타입 분리 + 상관관계 탐지
```

---

## 2. 변경 파일 목록 (핵심)

### 신규 추가 파일

| 파일 | 역할 |
|------|------|
| `ml_engine/sliding_window.py` | Redis ZSET 기반 슬라이딩 윈도우 (WINDOW_SIZE=60, TTL=600s) |
| `ml_engine/detectors.py` | Robust Z-score (MAD 기반) + Change Point 탐지기 |
| `ml_engine/isolation_forest.py` | IsolationForest (6차원 특징벡터, 동적 contamination) |
| `ml_engine/arima_forecaster.py` | ARIMA(1,1,1) 시계열 예측 + 피드백 루프 |
| `ml_engine/cusum_detector.py` | CUSUM 드리프트 탐지 (가스별 H_SIGMA 차등) |
| `ml_engine/pipeline.py` | 6종 탐지기 앙상블 통합 |
| `ml_engine/evaluator.py` | Proxy Label 성능 자동 평가 (Precision/Recall/F1) |
| `ml_engine/model_store.py` | 모델 영속화 (pickle/json) |
| `ml_engine/apps.py` | 앱 초기화 + 모델 캐시 복원 |
| `ml_engine/tests.py` | sliding_window 단위 테스트 4건 |
| `backoffice/views/ai.py` | 백오피스 AI 성능 모니터링 화면 |
| `fastapi_generator/ai_test.py` | AI 탐지 시뮬레이션 테스트 도구 |

### 삭제 파일

| 파일 | 삭제 이유 |
|------|----------|
| `alerts/services/anomaly_detector.py` | ml_engine으로 통합 교체 |
| `alerts/services/trend_predictor.py` | ml_engine으로 통합 교체 |
| `geofence/ai.bak/ttm_engine.py` | TTM zero-shot 모델 폐기 (정확도 불안정) |
| 각종 `.bak` 파일들 | 개발 중 임시 백업 파일 정리 |
| `verify_phase_*.py`, `debug_d*.py` | 개발 검증 스크립트 정리 |

### 주요 수정 파일

| 파일 | 변경 내용 요약 |
|------|--------------|
| `devices/views.py` | AI 파이프라인 연동, 에스컬레이션, 상관관계 탐지, 쿨다운 시스템 전면 재작성 |
| `alerts/models.py` | 알람 타입 5종 → 18종 확장, DB 인덱스 4개 추가 |
| `alerts/views.py` | AlarmViewSet 슬라이싱 버그 수정, 알람 그루핑 로직 추가 |
| `alerts/state_store.py` | TTL 5분 → 30분, Redis 오류 fallback 추가, preserve_pending 버그 수정 |
| `alerts/services/sensor_evaluator.py` | is_ai 파라미터 제거, sensor_ongoing 타입 분리, preserve_pending 버그 수정 |
| `geofence/anomaly_detector.py` | CUSUM baseline 기반 잔차 방식으로 전환, 임계치 20% 하향 |
| `accounts/views.py` | 오픈 리다이렉트 보안 취약점 수정 |
| `backoffice/notification_dispatcher.py` | @transaction.atomic 범위 최소화 (외부 I/O 잠금 제거) |
| `requirements.txt` | statsmodels >= 0.14 추가 |

---

## 3. 탐지기별 변경 상세

### 3-1. Z-score 탐지기 (신규)

- **이전**: 없음
- **현재**: Robust Z-score (MAD 기반)
  - 기존 mean/stdev 방식은 이상값이 윈도우에 섞이면 Z-score가 줄어드는 문제 → MAD(Median Absolute Deviation)로 교체
  - 공식: `σ = 1.4826 × MAD` (NIST 표준 환산식)
  - 임계: `|z| > 3.0`
  - 출력: `ANOMALY_WARNING` (caution)

### 3-2. Change Point 탐지기 (신규)

- **이전**: 없음
- **현재**: 슬라이딩 윈도우를 전반(prev 20개) vs 후반(curr 20개)으로 분할 비교
  - `mean_shift_score = |mean_curr - mean_prev| / (std_combined + EPS) > 2.5` → 평균 급변
  - `std_ratio = std_max / (std_min + EPS) > 2.5` → 분산 급변
  - 출력: `TREND_SHIFT` (caution)

### 3-3. Isolation Forest 고도화

| 항목 | 이전 (trend_predictor.py) | 현재 |
|------|--------------------------|------|
| 특징 벡터 차원 | 2차원 (value, 선형추세) | **6차원** (value, roll_mean, roll_std, diff, ratio, slope) |
| 학습 데이터 | 원본 그대로 | danger 초과값 제거 (개념 오염 방지) |
| 학습 방식 | 동기 (응답 블로킹) | **백그라운드 스레드** (탐지 공백 없음) |
| 동시 학습 제한 | 없음 | **세마포어 2개** (CPU 과부하 방지) |
| 재학습 주기 | 윈도우 크기 기반 (버그 있음) | **call_count 기반 50회** (단조 증가 보장) |
| contamination | 고정 0.03 | **동적 자동 조정** (FP rate 힌트 기반 ±0.005) |
| 모델 버전 관리 | 없음 | MODEL_VERSION=2 (차원 변경 시 자동 폐기) |
| 단독 발화 처리 | 무조건 ML_ANOMALY | score ≤ -0.3 → ML_ANOMALY / > -0.3 → ANOMALY_WARNING |

### 3-4. ARIMA 고도화

| 항목 | 이전 (anomaly_detector.py) | 현재 |
|------|---------------------------|------|
| 탐지 방식 | 잔차(residual) 3σ 초과 탐지 | **미래 예측값 임계치 비교** |
| 예측 선행 | 현재 패턴 이탈 | **10틱 앞 예측** (약 10초 리드타임) |
| 출력 | True/False | **PREDICTIVE_ALERT / PREDICTIVE_WARNING** 구분 |
| 학습 데이터 정제 | 없음 | danger 초과값 클리핑 (시계열 연속성 보존) |
| O2 지원 | 없음 | **양방향 클리핑** (16% ~ 23.5%) |
| 연속 실패 처리 | 없음 | **3회 연속 실패 → 조기 캐시 무효화** 재학습 |

### 3-5. CUSUM 드리프트 탐지기 (완전 신규)

**추가 이유**: Z-score/ChangePoint는 급변을 잘 잡지만 완만하게 서서히 상승하는 가스 농도는 놓침.
CUSUM은 누적합으로 이 패턴을 전용으로 탐지.

- 알고리즘: `S_high[t] = max(0, S_high[t-1] + (x - μ - k))`
- 파라미터: K_SIGMA=0.5, 가스별 차등 H_SIGMA

| 가스 | H_SIGMA | 선택 이유 |
|------|---------|----------|
| h2s | 2.5 | 즉각 생명 위협, 가장 민감하게 |
| no2, so2, o3, o2 | 3.0 | 좁은 위험 구간 |
| co, nh3, voc | 4.0 | 중간 속도 |
| co2 | 5.0 | 매우 완만한 누적, FP 최소화 |

- 200틱마다 baseline 재산출 (환경 변화 대응)
- 절대값 게이트: 안전 구간에서는 발화 억제 (FP 방지)
- 출력: `DRIFT_ALERT` (caution)

---

## 4. 아키텍처 변경

### 4-1. 병렬 처리 구조 도입

```python
# 이전 (AI_test_shj): 순차 처리
result = evaluate_sensor(...)
if result == 'normal':
    detect_anomaly(...)   # 블로킹
    predict_trend(...)    # 블로킹

# 현재 (AI_test_shj_2): 두 스레드 병렬
threading.Thread(target=_run_evaluate_sensor).start()  # 스레드 A
threading.Thread(target=_run_ai_pipeline).start()      # 스레드 B
```

효과: 응답 지연 감소, 임계치 알람과 AI 알람이 서로 블로킹하지 않음

### 4-2. 앙상블 투표 시스템

```
탐지기 동시 발화 수         →  출력 상태
──────────────────────────────────────────────
0개 모두 미탐지              →  NORMAL
1개 (CUSUM)                 →  DRIFT_ALERT
1개 (Z-score)               →  ANOMALY_WARNING
1개 (ChangePoint)           →  TREND_SHIFT
1개 (IF, score > -0.3)      →  ANOMALY_WARNING  ← 경계선 단독은 하향 (FP 억제)
1개 (IF, score ≤ -0.3)      →  ML_ANOMALY
2개 이상 동시 발화           →  ML_ANOMALY  ← 에스컬레이션
ARIMA (별도 예측 채널)       →  PREDICTIVE_ALERT / PREDICTIVE_WARNING
```

### 4-3. 에스컬레이션 시스템 (신규)

- 같은 `(device, metric, alarm_type)` 조합이 **300초 내 3회** 반복 → 레벨 상향 (caution → danger)
- 제외 타입: `ai_drift_alert`, `ai_predictive_*` (미래 예측/완만 드리프트에 danger 상향 부적절)

### 4-4. 다중 센서 상관관계 탐지 (신규)

| 패턴 | 탐지 조건 |
|------|----------|
| O2 변위 탐지 | O2 < 19.5% 동시에 가연성 가스(CO/H2S 등) 이상 발생 |
| 다중 가스 이상 | 120초 내 3종 이상 가스 동시 이상 |
| 공간 확산 탐지 | 반경 500m 내 장치들에서 8% 이상 농도 상승 동시 감지 |

---

## 5. 알람 타입 세분화

### 이전 (AI_test_shj)
```
ai_prediction  ←  모든 AI 알람이 하나의 타입
```

### 현재 (AI_test_shj_2)
```
# 센서 알람 (임계치 기반)
sensor_caution          ← 최초 주의 진입
sensor_danger           ← 최초 위험 진입 / 악화
sensor_ongoing          ← 지속 상태 재알림 [신규] (이전에는 sensor_caution 재사용)
sensor_recover_partial  ← 부분 회복
sensor_recover_normal   ← 완전 회복

# AI 알람 (ml_engine 기반)
ai_anomaly_warning      ← Z-score 통계 이상
ai_trend_shift          ← Change Point 급변
ai_ml_anomaly           ← Isolation Forest (앙상블 포함)
ai_drift_alert          ← CUSUM 완만 드리프트
ai_predictive_warning   ← ARIMA 예측 주의
ai_predictive_alert     ← ARIMA 예측 위험
ai_correlation          ← 다중 센서 상관관계 이상

# 작업자 알람 (worker_evaluator)
state_caution_enter / state_danger_enter / state_escalate
state_ongoing / state_recover_partial / state_recover_safe
```

---

## 6. 버그 수정 목록

| 번호 | 파일 | 버그 내용 | 수정 방법 |
|------|------|----------|----------|
| B1 | `alerts/views.py` | ViewSet `get_queryset()`에서 슬라이싱 → `retrieve(pk)` 시 TypeError | `list()` 오버라이드로 슬라이싱 이동 |
| B2 | `alerts/state_store.py` | Redis TTL 5분 → 단기 연결 끊김 시 상태 초기화로 중복 알람 발생 | TTL 30분으로 연장 |
| B3 | `alerts/services/sensor_evaluator.py` | `ongoing` 알람 발행 시 회복 카운터 초기화 → RECOVERY 1틱 지연 | `preserve_pending=True` 파라미터 추가 |
| B4 | `alerts/state_store.py` | Redis 오류 시 알람 파이프라인 전체 중단 | 오류 시 기본값 반환 fallback 추가 |
| B5 | `ml_engine/sliding_window.py` | Redis 연결 실패 시 예외 전파 | try/except → 빈 리스트/0/no-op 반환 |
| B6 | `workers/views.py` | ViewSet 슬라이싱 동일 버그 | B1과 동일 방식 수정 |
| B7 | `backoffice/notification_dispatcher.py` | `@transaction.atomic` 전체가 외부 I/O(SMTP/SMS) 포함 → DB 잠금 | 로그 생성만 atomic, provider.send()는 트랜잭션 외부 실행 |
| B8 | `geofence/anomaly_detector.py` | 지속 이상 상태에서 슬라이딩 윈도우가 이상값으로 채워져 잔차=0 | CUSUM baseline 기반 잔차로 전환 |
| B13 | `accounts/views.py` | 오픈 리다이렉트: `startswith('/')` 우회 가능 (`//evil.com`) | `url_has_allowed_host_and_scheme()` 적용 |

---

## 7. 성능 지표 (현재 상태)

> AI_test_shj에는 성능 측정 수단이 없어 직접 수치 비교 불가.
> 아래는 `integrate/shj-teamwork` 브랜치 기준, 2026-05-28 측정값 (최근 7일, 시뮬레이션 데이터).

### 7-1. Proxy Label 기반 성능 (최근 7일)

| 지표 | 이전 (AI_test_shj_2 초기) | 현재 (integrate/shj-teamwork) | 변화 |
|------|--------------------------|-------------------------------|------|
| **Precision (정밀도)** | 15.0% | **92.6%** | +77.6%p ↑ |
| **Recall (재현율)** | 90.0% | **96.1%** | +6.1%p ↑ |
| **F1 Score** | 25.7% | **94.3%** | +68.6%p ↑ |
| **FP Rate (오탐률)** | 85.0% | **7.4%** | -77.6%p ↓ |

| 항목 | 값 |
|------|-----|
| AI 알람 총계 | 24,641건 |
| TP (사전 탐지 성공) | 22,827건 |
| FP (오탐) | 1,814건 |
| FN (미탐지) | 187건 |
| 실제 threshold 알람 | 4,799건 |

### 7-2. 탐지기별 Precision

| 탐지기 | 이전 | 현재 | 변화 | 발화 건수 |
|--------|------|------|------|-----------|
| ai_predictive_alert | 25.0% | **100.0%** | +75%p ↑ | 38건 |
| ai_predictive_warning | 55.6% | **100.0%** | +44.4%p ↑ | 207건 |
| ai_correlation | 13.0% | **99.8%** | +86.8%p ↑ | 1,659건 |
| ai_drift_alert (CUSUM) | 31.8% | **97.5%** | +65.7%p ↑ | 6,903건 |
| ai_ml_anomaly (IF) | 13.6% | **89.8%** | +76.2%p ↑ | 13,829건 |
| ai_trend_shift (CP) | 14.4% | **89.5%** | +75.1%p ↑ | 1,262건 |
| ai_anomaly_warning (Z) | 17.5% | **86.3%** | +68.8%p ↑ | 743건 |

### 7-3. Precision이 크게 향상된 주요 원인

1. **ai_correlation 99.8%**: `related_device_id` 필드 추가로 proxy 평가 로직의 device_id 불일치 해소 (이전: 전력 센서 ID로 가스 threshold 알람 매칭 시도 → 전부 FP)
2. **쿨다운 및 STD_RATIO_THRESHOLD 조정**: 단발 spike에 의한 FP 대폭 억제
3. **IF contamination 자동 조정**: FP rate 기반 ±0.005 점진 튜닝

### 7-4. ARIMA 예측 정확도

| 지표 | 이전 | 현재 | 변화 |
|------|------|------|------|
| 전체 예측 수 | 28건 | **145건** | +117건 |
| 성공률 | 25.0% | **90.3%** | +65.3%p ↑ |

| 센서 | 예측 수 | 정확도 |
|------|---------|--------|
| CO | 84건 | **86.9%** |
| CO₂ | 49건 | **95.9%** |
| O₃ | 8건 | **87.5%** |
| NH₃ / O₂ / VOC | 4건 | **100%** |

---

## 8. 다음 개선 과제

> 현재 시뮬레이션 데이터 기준 수치. 실제 현장 배치 후 재측정 필요.

| 우선순위 | 항목 | 현재 값 | 목표 | 예상 효과 |
|----------|------|---------|------|----------|
| 운영 전환 시 | `_GAS_COOLDOWN_SEC` | 30초 | 120초 | 가스 AI 알람 중복 억제 강화 |
| 운영 전환 시 | `_BASE_COOLDOWN_SEC` | 10초 | 60초 | 전력·에스컬레이션 중복 억제 강화 |
| 운영 전환 시 | `REBASELINE_TICKS` | 200틱 | 100틱 | 환경 변화 반응 속도 개선 |
| 운영 전환 시 | IF/ARIMA `RETRAIN_INTERVAL` | 50회 | 25회 | 모델 적응 속도 개선 |
| 현장 데이터 후 | contamination | 0.030 (자동 조정 중) | 실데이터 기반 결정 | ai_ml_anomaly FP 조정 |
| 현장 데이터 후 | ARIMA 신뢰도 | 145건 기준 | 500건+ 축적 | CO 86.9% → 90%+ 목표 |

---

## 부록: 커밋 이력

```
874d685  ai 성능 test 및 알람 디버깅
4e0fd7b  chore: 미커밋 변경사항 정리 (알람 시스템 재정립 후속)
2f9ab15  fix: 알람 시스템 버그 수정 + 기술부채 A 처리
9a341a5  feat: 알람 시스템 재정립 + 시나리오 안정화 + AI 정확도 개선
```

총 변경: **77개 파일**, +5,931줄 / -4,608줄
