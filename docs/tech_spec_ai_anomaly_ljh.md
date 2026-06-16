# AI 이상탐지 & 이벤트 현황 UI 기술 명세

**담당자:** 이준호 (`dev_ljh`)  
**브랜치:** `dev_ljh`  
**최종 수정:** 2026-05-29

---

## 목차

1. [개요](#1-개요)
2. [Isolation Forest 이상탐지](#2-isolation-forest-이상탐지)
3. [ARIMA 시계열 예측 이상탐지](#3-arima-시계열-예측-이상탐지)
4. [AI 알람 DB 저장 연동](#4-ai-알람-db-저장-연동)
5. [이벤트 현황 3탭 UI](#5-이벤트-현황-3탭-ui)
6. [전체 데이터 흐름](#6-전체-데이터-흐름)
7. [변경 파일 목록](#7-변경-파일-목록)

---

## 1. 개요

센서 데이터의 이상을 두 가지 독립적인 방법으로 탐지하고, 감지 결과를 기존 알람 파이프라인과 통합하는 작업을 담당했다. 탐지 결과는 DB에 저장되어 이력이 보존되며, WebSocket을 통해 대시보드에 실시간 반영된다.

**담당 범위 요약**

| 영역 | 내용 | 파일 |
|------|------|------|
| AI 백엔드 | Isolation Forest 이상탐지 모듈 | `ml/anomaly_detector.py` |
| AI 백엔드 | ARIMA 시계열 예측 이상탐지 모듈 | `ml/arima_predictor.py` |
| 백엔드 연동 | AI 알람 DB 저장 + WebSocket 발행 | `devices/views.py` |
| 모델 수정 | `ai_anomaly` 알람 타입 추가 | `alerts/models.py` |
| 프론트엔드 | 이벤트 현황 3탭 UI 전체 재작성 | `section_10_events.*` |

---

## 2. Isolation Forest 이상탐지

**파일:** `SenSa/ml/anomaly_detector.py`

### 2.1 목적

단일 센서 값의 임계치 초과 여부만 판단하는 기존 방식과 달리, **여러 센서 값의 조합 패턴**이 평소와 다를 때 이상으로 판단한다. 예를 들어 CO는 정상이지만 O₂와 온도가 동시에 비정상적인 방향으로 움직이는 경우를 감지할 수 있다.

### 2.2 동작 원리

Isolation Forest는 랜덤 트리 분할을 통해 데이터 포인트를 고립시킨다. 이상 데이터는 정상 데이터 무리에서 떨어져 있기 때문에, 더 적은 분할 횟수만으로 고립된다. 이 분할 횟수(depth)가 짧을수록 이상 점수가 낮아진다.

### 2.3 클래스 구조

```
SensorAnomalyDetector          ← device 1개 담당
├── _window: deque(maxlen=200) ← 최근 측정값 슬라이딩 윈도우
├── _model: IsolationForest    ← 학습된 모델
└── _tick: int                 ← 수신 횟수 (재학습 주기 추적)

_registry: dict[device_id → SensorAnomalyDetector]  ← 전역 싱글턴
```

### 2.4 설정값

| 파라미터 | 값 | 설명 |
|----------|----|------|
| `MIN_SAMPLES` | 30 | 최소 학습 샘플 수. 미만이면 탐지 건너뜀 |
| `WINDOW_SIZE` | 200 | 슬라이딩 윈도우 크기 (deque maxlen) |
| `RETRAIN_EVERY` | 20 | 20번 수신마다 모델 재학습 |
| `CONTAMINATION` | 0.05 | 이상치 비율 추정 (5%) |
| `n_estimators` | 100 | 트리 개수 |

### 2.5 입력 피처

- **가스 센서:** `co`, `h2s`, `co2`, `o2`, `no2`, `so2`, `o3`, `nh3`, `voc` (9차원 벡터)
- **전력 센서:** `current`, `voltage`, `watt` (3차원 벡터)

값이 하나라도 `None`이면 해당 틱은 건너뛴다.

### 2.6 이상 감지 시 반환값

```python
{
    'device_id':      'sensor_01',
    'sensor_type':    'gas',
    'type':           'anomaly_detected',
    'alarm_level':    'caution',
    'anomaly_score':  -0.1234,      # 낮을수록 이상
    'worst_feature':  'co',         # z-score 가장 높은 피처
    'message':        '[이상탐지] sensor_01 — 패턴 이상 감지 (score: -0.123)',
}
```

`worst_feature`는 슬라이딩 윈도우 평균 대비 z-score가 가장 높은 피처를 반환한다. 알람 메시지에서 어떤 값이 주로 벗어났는지 참고 정보로 쓴다.

### 2.7 외부 진입점

```python
from ml.anomaly_detector import detect_anomaly

result = detect_anomaly(device_id, sensor_type, values)
# result: None (정상 또는 샘플 부족) | dict (이상 감지)
```

`device_id`별 `SensorAnomalyDetector` 인스턴스는 `_registry`에 싱글턴으로 관리된다. 프로세스가 살아있는 동안 슬라이딩 윈도우와 학습 모델이 유지된다.

---

## 3. ARIMA 시계열 예측 이상탐지

**파일:** `SenSa/ml/arima_predictor.py`

### 3.1 목적

Isolation Forest가 **공간축**(여러 센서 조합)의 이상을 잡는다면, ARIMA는 **시간축**(한 센서의 흐름)에서 예측과 실제의 괴리를 탐지한다. 현재 데이터 추세로 미래 값을 예측해, 임계치 진입이 예상될 때 사전 경고를 발행하기도 한다.

> **팀원 버전과의 관계:** `alerts/services/anomaly_detector.py`에 팀원이 작성한 ARIMA 버전이 있다. 해당 버전이 `sensor_evaluator.py`를 통해 DB 저장까지 연결되어 있어 더 완성도가 높으므로, `devices/views.py`에서의 직접 호출은 제거하고 팀원 버전으로 통합했다. `ml/arima_predictor.py`는 독립 참고 모듈로 유지된다.

### 3.2 탐지 방식 2가지

#### 방식 1 — 잔차 이상 (Residual Anomaly)

이전 틱에서 예측한 값과 이번 틱의 실제 값을 비교한다. 잔차가 최근 잔차 분포의 3σ를 초과하면 이상으로 판단한다.

```
z = (|실제 - 예측| - 잔차_평균) / 잔차_표준편차
z > 3.0  →  이상 감지
```

#### 방식 2 — 예측 사전 경고 (Forecast Pre-warning)

현재 윈도우로 향후 5스텝을 예측해, 예측값이 `caution` 또는 `danger` 임계치에 진입하면 지금 시점에 경고를 발행한다.

```
max(forecast[0..4]) >= THRESHOLDS[key]['danger']   →  alarm_level = 'danger'
max(forecast[0..4]) >= THRESHOLDS[key]['caution']  →  alarm_level = 'caution'
```

### 3.3 설정값

| 파라미터 | 값 | 설명 |
|----------|----|------|
| `MIN_SAMPLES` | 30 | 최소 학습 샘플 수 |
| `WINDOW_SIZE` | 100 | 슬라이딩 윈도우 |
| `RETRAIN_EVERY` | 20 | 재학습 주기 |
| `FORECAST_STEPS` | 5 | 사전 경고용 예측 스텝 수 |
| `RESIDUAL_SIGMA` | 3.0 | 잔차 z-score 임계치 |

### 3.4 대상 키

```python
PRIMARY_KEY = {'gas': 'co', 'power': 'watt'}
```

가스 센서는 CO, 전력 센서는 watt를 대표 시계열로 사용한다.

### 3.5 ARIMA 모델 선택

```python
for order in [(2, 1, 2), (1, 1, 1)]:
    try:
        self._model_fit = ARIMA(data, order=order).fit()
        return
    except Exception:
        continue
```

`ARIMA(2,1,2)`로 먼저 시도하고, 수렴 실패 시 `ARIMA(1,1,1)`로 폴백한다.

### 3.6 임계치 테이블

`alerts/services.py`의 `GAS_THRESHOLDS`와 동기화된 값을 사용한다.

| 가스 | caution | danger |
|------|---------|--------|
| CO | 25 ppm | 200 ppm |
| H2S | 10 ppm | 50 ppm |
| CO₂ | 1000 ppm | 5000 ppm |
| NO₂ | 3 ppm | 5 ppm |
| SO₂ | 2 ppm | 5 ppm |
| NH₃ | 25 ppm | 50 ppm |
| VOC | 0.5 ppm | 2.0 ppm |

---

## 4. AI 알람 DB 저장 연동

**파일:** `SenSa/devices/views.py`, `SenSa/alerts/models.py`

### 4.1 배경

Isolation Forest 도입 초기에는 WebSocket으로만 이상 감지 이벤트를 전송했다. 이 방식은 페이지 새로고침 시 알람이 사라지고, 읽음 처리·이력 조회 등 기존 알람 기능을 사용할 수 없다는 문제가 있었다. 이를 해결하기 위해 AI 감지 결과도 기존 `Alarm` 모델에 저장하도록 수정했다.

### 4.2 알람 타입 추가

`alerts/models.py`의 `ALARM_TYPE_CHOICES`에 `ai_anomaly` 타입을 추가했다.

```python
# alerts/models.py
ALARM_TYPE_CHOICES = [
    ...
    ('ai_anomaly', 'AI 이상탐지'),  # 추가
]
```

마이그레이션: `alerts/migrations/0003_add_ai_anomaly_alarm_type.py`

### 4.3 devices/views.py 수정 — SensorDataView.post()

센서 데이터 수신 엔드포인트(`POST /devices/sensor-data/`)에서 기존 임계치 판정 후 Isolation Forest 탐지를 추가로 실행한다.

```python
# devices/views.py — SensorDataView.post() 내부 (L154-175)

# 공통: Device 상태 갱신 + WebSocket 전송 (기존 흐름 유지)
device.status = s
device.save(update_fields=['status', 'last_value'])
publish_sensor_update({...})

# ── 추가된 부분 ──────────────────────────────────────
anomaly = detect_anomaly(device.device_id, sensor_type, payload_values)
if anomaly:
    from alerts.models import Alarm
    from realtime.publishers import publish_alarm

    alarm_obj = Alarm.objects.create(
        alarm_type='ai_anomaly',
        alarm_level=anomaly.get('alarm_level', 'caution'),
        device_id=device.device_id,
        sensor_type=sensor_type,
        message=anomaly.get('message', '[AI 이상탐지] 패턴 이상 감지'),
    )
    publish_alarm({
        'alarm_id':    alarm_obj.id,
        'alarm_type':  'ai_anomaly',
        'alarm_level': alarm_obj.alarm_level,
        'device_id':   device.device_id,
        'sensor_type': sensor_type,
        'message':     alarm_obj.message,
        'is_read':     False,
        'created_at':  alarm_obj.created_at.isoformat(),
    })
```

### 4.4 publish_alarm() 경로

`publish_alarm()`은 `realtime/publishers.py`에 정의된 얇은 래퍼 함수다. Django Channels의 Channel Layer를 통해 `dashboard.alarms` 그룹에 `alarm.new` 이벤트를 발행한다.

```
publish_alarm(dict)
  └─ _send("dashboard.alarms", "alarm.new", payload)
       └─ channel_layer.group_send()   ← Redis Channel Layer
            └─ WebSocket Consumer
                 └─ SenSa.emit('alarm')  ← 프론트엔드
```

`/dashboard/api/alarm/` GET 엔드포인트는 DB를 조회하므로, 저장된 AI 알람도 페이지 로드 시 자동으로 불러온다.

---

## 5. 이벤트 현황 3탭 UI

**파일:**
- `SenSa/templates/dashboard/sections/section_10_events.html`
- `SenSa/static/js/dashboard/section_10_events.js`
- `SenSa/static/css/dashboard/section_10_events.css`

### 5.1 배경

기존에는 모든 알람이 단일 목록에 표시되었다. 위험/주의/AI탐지 성격이 다른 알람이 뒤섞여 있어 운영자가 원하는 알람을 찾기 어려웠다. 이를 세 탭으로 분리했다.

### 5.2 탭 구성

| 탭 | 조건 | 색상 |
|----|------|------|
| 🔴 위험 | `alarm_level`이 `danger` 또는 `critical`이고 AI 알람이 아닌 것 | `--color-danger` |
| ⚠️ 주의 | `alarm_level`이 `caution`이고 AI 알람이 아닌 것 | `--color-caution` |
| 🤖 AI탐지 | `alarm_type === 'ai_anomaly'` 또는 메시지에 `[이상탐지]`/`[ARIMA]` 포함 | `#a78bfa` |

### 5.3 resolveTab() — 탭 분류 로직

```javascript
// section_10_events.js
function resolveTab(alarm) {
    var isAI = alarm.alarm_type === 'ai_anomaly' ||
               (alarm.message && (
                   alarm.message.indexOf('[이상탐지]') !== -1 ||
                   alarm.message.indexOf('[ARIMA]') !== -1
               ));
    if (isAI) return 'ai';
    if (alarm.alarm_level === 'danger' || alarm.alarm_level === 'critical') return 'danger';
    return 'caution';
}
```

AI 알람 여부를 먼저 확인하는 이유는 `alarm_type`이 설정되지 않은 WebSocket 직접 수신 알람(`anomalyDetected` 이벤트)에서도 메시지 본문으로 AI탭에 정확히 배치하기 위해서다.

### 5.4 switchAlarmTab() — 탭 전환

```javascript
window.switchAlarmTab = function(tab) {
    document.querySelectorAll('.alarm-tab').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    document.querySelectorAll('.alarm-tab-panel').forEach(function(panel) {
        panel.style.display = 'none';
    });
    var target = document.getElementById('alarm-list-' + tab);
    if (target) target.style.display = 'block';
};
```

### 5.5 상태 관리

```javascript
var unreadCount = 0;
var tabCounts   = { danger: 0, caution: 0, ai: 0 };
```

- **탭별 최대 30개 유지:** 목록이 30개를 초과하면 가장 오래된 항목을 제거한다.
- **미읽음 카운트:** 클릭 시 `unread` 클래스 제거 + `PATCH /api/alarm/<id>/read/` 호출.
- **모두 읽음:** `PATCH /api/alarm/read_all/` 호출 후 전체 `unread` 클래스 제거.

### 5.6 알람 수신 경로 2가지

```javascript
// 경로 1: DB 저장된 알람 (페이지 로드 시)
SenSa.on('alarm', function(alarm) {
    addAlarmToPanel(alarm, false);
    if (alarm.alarm_level !== 'info') showBanner(alarm);
});

// 경로 2: IF WebSocket 직접 수신 (anomalyDetected 이벤트)
SenSa.on('anomalyDetected', function(payload) {
    var alarm = {
        alarm_id:    null,
        alarm_type:  'ai_anomaly',   // resolveTab이 'ai' 탭으로 분류
        alarm_level: payload.alarm_level || 'caution',
        message:     payload.message || '[이상탐지] 패턴 이상 감지',
        is_read:     false,
        created_at:  new Date().toISOString(),
    };
    addAlarmToPanel(alarm, false);
    showBanner(alarm);
});
```

### 5.7 CSS 주요 클래스

```css
/* 탭 버튼 */
.alarm-tab[data-tab="danger"].active   { border-bottom-color: var(--color-danger); }
.alarm-tab[data-tab="caution"].active  { border-bottom-color: var(--color-caution); }
.alarm-tab[data-tab="ai"].active       { border-bottom-color: #a78bfa; }

/* 탭별 활성 카운트 뱃지 */
.alarm-tab[data-tab="ai"].active .tab-count { background: #a78bfa; color: #fff; }

/* 탭 패널 */
.alarm-tab-panel { flex: 1; overflow-y: auto; padding: 4px 10px 10px; }
```

---

## 6. 전체 데이터 흐름

```
FastAPI Generator
  └─ POST /devices/sensor-data/
       │
       ├─ classify_gas() / classify_power()     ← 기존 임계치 판정
       ├─ SensorData.objects.create()           ← DB 저장
       ├─ publish_sensor_update()               ← 센서 패널 실시간 갱신
       │
       └─ detect_anomaly()                      ← [추가] IF 이상탐지
            │
            ├─ 정상 또는 샘플 부족 → None → 종료
            │
            └─ 이상 감지 → dict 반환
                 │
                 ├─ Alarm.objects.create(alarm_type='ai_anomaly')  ← DB 저장
                 └─ publish_alarm()
                      └─ Channel Layer (Redis)
                           └─ WebSocket → 브라우저
                                └─ SenSa.emit('alarm')
                                     └─ section_10_events.js
                                          └─ resolveTab() → 'ai' 탭에 삽입
```

---

## 7. 변경 파일 목록

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `SenSa/ml/anomaly_detector.py` | 신규 생성 | Isolation Forest 이상탐지 모듈 |
| `SenSa/ml/arima_predictor.py` | 신규 생성 | ARIMA 시계열 예측 이상탐지 모듈 |
| `SenSa/devices/views.py` | 수정 | IF 이상탐지 호출 + DB 저장 + publish_alarm 연동 |
| `SenSa/alerts/models.py` | 수정 | `ai_anomaly` 알람 타입 추가 |
| `SenSa/alerts/migrations/0003_add_ai_anomaly_alarm_type.py` | 신규 생성 | 마이그레이션 |
| `SenSa/templates/dashboard/sections/section_10_events.html` | 전체 재작성 | 3탭 구조로 변경 |
| `SenSa/static/js/dashboard/section_10_events.js` | 전체 재작성 | resolveTab, switchAlarmTab, tabCounts 구현 |
| `SenSa/static/css/dashboard/section_10_events.css` | 수정 | 탭 스타일 추가 |
| `SenSa/static/js/dashboard/base.js` | 수정 | main 브랜치 병합 — anomaly.detected 케이스 유지 |
