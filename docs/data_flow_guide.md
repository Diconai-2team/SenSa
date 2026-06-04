# SenSa 데이터 흐름 & Grafana 분석 가이드

> 처음 보는 사람도 이해할 수 있도록, **정상 운영 흐름**과 **op_multi 시나리오 흐름**을
> 각각 그려보고, 각 단계를 Grafana의 어떤 패널로 분석하는지 정리한 문서입니다.

---

## 0. 먼저 — 등장인물 (이 시스템의 7명)

| 이름 | 실제 정체 | 비유 |
|---|---|---|
| **Sensor** | FastAPI 제너레이터(`sensa_generator`)가 진짜 센서처럼 1초마다 값 생성 | 🛰️ 현장 감지기 |
| **API** | Django의 `SensorDataView.post` | 🏢 접수 창구 |
| **DB** | PostgreSQL (`SensorData`, `Alarm`, `AIPrediction` 테이블) | 📒 장부 |
| **Celery** | 백그라운드 작업 일꾼(`sensa_celery`) | 👷 뒤에서 일하는 직원 |
| **AIResult / AlarmEvent** | `AIPrediction`(예측), `Alarm`(알람) 레코드 | 🚨 판정 결과지 |
| **WebSocket** | Django Channels `group_send` | 📡 실시간 사내방송 |
| **Dashboard** | 프론트엔드 화면 + **Grafana**(관제 지표) | 🖥️ 관제 모니터 |

> **중요한 구분**: 프론트 Dashboard(지도·실시간 화면)와 Grafana(숫자 지표 모니터링)는 다릅니다.
> 이 문서의 "Grafana 분석"은 후자입니다.

---

## 1. 기본 데이터 흐름 (정상 운영)

### 흐름도

```
🛰️ Sensor (1초마다)
   │  HTTP POST {device_id, co, h2s, ...}
   ▼
🏢 API  SensorDataView.post
   │  ① 값 검증(_get_float: 음수/이상치 거부)
   │  ② classify_gas — 임계치로 normal/caution/danger 판정
   │  ③ detect_anomaly — ARIMA 이상 탐지(보조)
   │  ④ predict_trend — IsolationForest 추세 예측
   ▼
📒 DB  SensorData.objects.create()   ← 측정값 1행 저장
   ▼
🚨 evaluate_sensor()  (Django 안에서 즉시 실행 — 동기)
   │  상태 전이 확정되면:
   │     • Alarm.objects.create()        (AlarmEvent)
   │     • AIPrediction.objects.create() (AIResult, 예측 시)
   │     • 메트릭 .inc()  ← Grafana가 보는 숫자!
   ▼
📡 WebSocket  publish_sensor_update / publish_alarm
   │  Channels group_send → 브라우저로 실시간 푸시
   ▼
🖥️ 프론트 Dashboard  (지도·그래프 갱신)

         ┌─ 👷 Celery (옆에서 비동기로) ─────────────────┐
         │  • send_external_notification (Slack/Discord)  │
         │  • 모델 fit(ARIMA/IF) 백그라운드                │
         │  • tick_zones (30초마다 zone 반경/만료)        │
         └────────────────────────────────────────────────┘
```

### ⚠️ 꼭 알아야 할 핵심 2가지

1. **알람 판정(evaluate_sensor)은 Celery가 아니라 Django 요청 안에서 "즉시" 일어납니다.**
   `DB → Celery → AlarmEvent`는 개념적 단순화이고, 실제로 Celery가 맡는 건
   **외부알림 발송·무거운 모델 학습·주기적 zone 관리**입니다.
   → 정상 흐름에선 Django 패널이 주로 움직이고, Celery 패널은 알림/시나리오 때 움직입니다.
2. **카운터는 "일이 실제로 일어나야" 숫자가 생깁니다.**
   정상값만 흐르면 알람이 안 생기므로 알람 패널은 0입니다(고장 아님).

### 각 단계 → Grafana 어디서 보나

| 단계 | Grafana 패널 | PromQL / 봐야 할 값 |
|---|---|---|
| 🛰️ Sensor가 쏘는 양 | **Generator publish 속도** | `rate(sensa_generator_publish_total[1m])` |
| 🛰️ 쏘는 지연 | **Generator publish 95p latency** | `histogram_quantile(0.95, ...generator_publish_duration...)` |
| 🏢 API 수신 | **Django 요청 수** / **API 수신 성공률** | `rate(django_http_requests_total_by_method_total[1m])`, `sensa_api_requests_total` |
| 🏢 API 응답속도/에러 | **Django p95 응답시간** / **5xx 에러율** | `histogram_quantile(0.95, ...)` / 5xx 비율 |
| 📒 DB 저장 | **DB 저장 성공률** | `sensa_db_save_total{result="success"}` 비율 |
| 📊 센서 실측값(신규) | **센서 가스/전력 실측값(G1)** | `sensa_sensor_value{device_id, sensor}` |
| 🚨 알람 생성 | **알람 생성 분당 속도** | `sum by(alarm_level)(rate(sensa_alarm_created_total[1m]))` |
| 🚨 중복 알람 억제 | **60s Throttle 차단** | `rate(sensa_alarm_throttled_total[1m])` |
| 📡 WebSocket | **WebSocket 연결 수 / 전송 성공률** | `sensa_ws_connections_active`, `sensa_ws_send_total` 성공률 |
| 👷 Celery 일감 | **Celery task 처리 속도** | `rate(sensa_celery_task_total[5m])` by task_name/state |
| 👷 외부알림 | **외부알림 발송(Slack/Discord)** | `sensa_celery_task_total{task_name="...send_external_notification"}` |

> **정상일 때 그림**: publish/요청/DB저장/WebSocket은 꾸준히 흐르고,
> 알람·throttle·외부알림은 거의 0. 이게 "건강한 baseline"입니다.

---

## 2. op_multi 시나리오 흐름

### op_multi가 하는 일 (한 문장)
**중심부 센서 1곳에서 강한 CO 누출(280ppm)을 5분간 일으켜, 주변 센서들까지 위험권에
들어오고 zone이 커지며 critical로 승격되는** 다중 확산 시연입니다.
(`geofence/scenarios/operational_multi.py`)

### 정상 흐름과 결정적 차이
- 데이터를 **제너레이터가 아니라 Celery가 직접** 만들어 DB에 넣습니다(POST 우회).
- 한 센서가 아니라 **여러 센서**가 동시에 오릅니다(convex hull zone).
- CO 280ppm은 danger(200) 초과 → 센서가 **danger 상태**까지 갑니다.

> ⚠️ **중요 — op_multi는 critical/Discord를 발생시키지 않습니다.**
> - 센서 알람은 **caution/danger만** 생성합니다(critical 없음).
> - "critical"은 오직 **GeoFence zone tier 승격**(`upgraded_to_critical`)에서만 나오고,
>   그 조건은 **이웃 가스 센서 3개 이상이 confirm**(`MIN_CONFIRMING_FOR_CRITICAL=3`)입니다.
> - 그런데 **op_* 시나리오 zone은 tier 자동 승격에서 의도적으로 제외**됩니다
>   ([zone_lifecycle.py](../SenSa/geofence/zone_lifecycle.py)의 `scenario_op_` 격리).
> - 따라서 op_multi는 zone critical에 도달하지 못하고, **Discord 외부알림도 나가지 않습니다.**
> - 실제 critical→Discord를 보려면 **CLI `multi_leak` 시나리오**를 써야 합니다(아래 별도 표 참고).

### 흐름도

```
[트리거 1회]  POST /scenarios/op/run/op_multi/
   ▼
🧠 scenario.execute()
   ① pick_source_sensor()      중심부 센서 1개 선택
   ② diffusion_radius(co,45s)  그레이엄 확산 시작 반경 계산
   ③ _compute_affected()       반경 안의 주변 센서 자동 검출(거리별 강도 차등)
   ④ _create_zone()            convex hull polygon + current_radius_px
   ⑤ 영향 센서마다 👷 sustain_spike_task 큐잉   ← 여러 체인!
   ▼
👷 Celery sustain_spike_task  (영향 센서 × 0.5초마다 재귀)
   │  5단계 곡선:
   │   ramp_up 30s (base→280) → sustain 60s(danger 정점)
   │   → ramp_down 60s(자연복귀) → 종료
   │  매 step:
   │   • 📒 SensorData.create() (status를 농도로 판정)
   │   • 📡 publish_sensor_update() → WebSocket
   │   • 🚨 evaluate_sensor() → Alarm(caution/danger) + 메트릭  ← critical 아님
   ▼
👷 Celery tick_zones (30초마다, 별도)
   • 📒 update_zone_radius() — 반경 성장(확산 진행)
   • 새로 반경에 든 센서 검출 → 추가 spike 큐잉(영향 센서 증가)
   • expire_zones() — TTL(180s) 만료 시 zone 비활성화
   ▼
📡 WebSocket('expired') → 🖥️ 프론트에서 zone 제거
```

### op_multi 각 단계 → Grafana

| 시점 | 무슨 일 | 패널 | 봐야 할 신호 |
|---|---|---|---|
| **0초** | zone 생성 | **zone 라이프사이클(G7)** | `created` 1건 / `sensa_zone_active_dynamic` +1 |
| **0~30초** | 가스 ramp-up | **센서 가스 실측값(G1)** | 중심 센서 `co`가 base→280으로 급상승, 이웃 센서들도 같이 상승(차등) |
| **0초~** | spike 주입 부하 | **Celery task 처리 속도** | `sustain_spike_task` rate가 여러 체인만큼 높게 급증 |
| **30초~** | 확산 반경 성장 | **zone 확산 반경(G4)** | `sensa_zone_radius_px{zone_id=...}`가 30초 tick마다 우상향 |
| **30초~** | 영향권 확대 | **zone 영향 센서 수(G5)** | `sensa_zone_affected_sensors`가 2 이상(op_single은 1) |
| **~30초 후** | 상태 전이 | **알람 생성 분당 속도** | `alarm_level="caution"`→`"danger"` 증가 (**critical은 안 나옴** — op_*는 zone 승격 제외) |
| **지속** | 중복 억제 | **60s Throttle 차단** | `sensa_alarm_throttled_total` 누적 증가 |
| ~~외부 통지~~ | ❌ 해당 없음 | ~~외부알림 발송~~ | op_multi는 critical 미발생 → **Discord 안 나감**(multi_leak에서만 발생) |
| **상시** | 실시간 방송 | **WebSocket 전송 성공률** | 100% 유지(끊기면 방송 장애) |
| **3분(180초)** | 종료 | **zone 라이프사이클(G7)** | `expired` 1건 → 반경/영향센서 series 소멸, 활성 zone -1 |

---

## 3. Grafana 실전 분석 가이드 (이 순서로 보세요)

### 화면 보는 순서 (위→아래로 "이야기"가 됨)
1. **zone 라이프사이클(G7)** 에서 `created` 확인 → "시나리오 시작됨"
2. **센서 가스 실측값(G1)** 에서 어느 센서·무슨 가스가 오르는지 → "어디서 무엇이"
3. **zone 확산 반경(G4) + 영향 센서 수(G5)** → "얼마나 넓게 번지나"
4. **Celery task 처리 속도** → "주입이 정상 처리되나"
5. **알람 생성 분당 속도** → "위험 판정·경보가 나가나"(critical 보면 op_multi)
6. **WebSocket / 외부알림** → "현장·외부로 전파되나"
7. **Django p95 / 5xx / DB 저장 성공률** → "이 부하에도 본 시스템이 멀쩡한가"(회귀 확인)

### op_multi를 한눈에 식별하는 "지문"
```
✔ 센서 가스값: 여러 device의 co가 동시에 ↑ (한 개 아님)
✔ zone 영향 센서 수(G5): 2 이상
✔ 알람 레벨: caution/danger까지 (critical 아님)
✔ 지속시간: 약 3분(180초)
✔ Celery sustain_spike_task: 체인 수만큼 높은 rate
```
→ 이 5개가 동시에 보이면 확실히 **op_multi**입니다.
(op_single/op_h2s는 센서 1개·영향 1, h2s는 `co` 대신 `h2s`가 오름)

### critical → Discord를 보려면: CLI `multi_leak` (op_multi 아님)
op_* 시나리오는 zone tier 승격에서 제외되므로 critical/Discord가 안 납니다.
**진짜 critical→Discord 흐름**은 CLI 회귀 시나리오 `multi_leak`에서만 나옵니다:
```bash
docker exec sensa_django python manage.py run_scenario multi_leak
```
| 단계 | 패널/신호 |
|---|---|
| zone 생성 | `sensa_zone_event_total{event_type="created"}` |
| 이웃 센서 3개 confirm → tier 승격 | `sensa_zone_event_total{event_type="upgraded_to_critical"}` 1건 |
| critical 승격 → 외부 통지 | **외부알림 발송** 패널 `send_external_notification` task → 🔴 Discord 전송 |

### 초보자가 자주 혼동하는 포인트
- **"Django 요청 수가 안 늘어요"** → 정상입니다. op_*의 데이터는 Celery가 DB에 직접
  넣어서 Django POST를 안 탑니다. 부하는 **Celery 패널**로 보세요.
- **"알람 패널이 0이에요"** → 이상 이벤트가 없으면 0이 맞습니다(고장 아님).
  시나리오를 돌리거나 위험값이 떠야 채워집니다.
- **"zone 반경/영향센서 패널이 비어요"** → 활성 동적 zone이 있을 때만 나옵니다.
  시나리오 종료(expired) 후엔 자연히 사라집니다(정상).

---

## 한 장 요약

| | 정상 흐름 | op_multi |
|---|---|---|
| 데이터 출처 | 🛰️ 제너레이터 POST | 👷 Celery 직접 주입 |
| 주 부하 패널 | Django 요청/DB | **Celery task** |
| 센서값(G1) | 평탄한 baseline | 여러 센서 co 동반 급상승 |
| zone(G4/G5) | 없음 | 반경 성장 + 영향센서 2+ |
| 알람 | 거의 0 | caution→danger (critical 아님) |
| Discord(critical) | — | ❌ 안 나감 (multi_leak에서만 발생) |
| 종료 | — | 3분 후 `expired` |

> **핵심 한 줄**: "정상은 Django·DB가 잔잔히 흐르고, op_multi는 Celery가 데이터를 만들어
> zone이 커지고 센서가 danger까지 올라간다 — 그 과정을 G7→G1→G4/G5→알람 순서로 본다.
> 단 **critical/Discord는 op_multi가 아니라 multi_leak(이웃 센서 3개 confirm)에서만** 나온다."

---

## 부록 — 신규 패널(G1/G4/G5/G7) 메트릭 정의

| 패널 | 메트릭 | 정의 위치 |
|---|---|---|
| G1 센서 실측값 | `sensa_sensor_value{device_id, sensor, sensor_type}` | `devices/metrics.py` SensorValueCollector |
| G4 zone 확산 반경 | `sensa_zone_radius_px{zone_id, gas_type, tier}` | `geofence/metrics.py` ZoneStateCollector |
| G5 zone 영향 센서 수 | `sensa_zone_affected_sensors{zone_id, gas_type}` | `geofence/metrics.py` ZoneStateCollector |
| G7 zone 라이프사이클 | `sensa_zone_event_total{event_type}` | `geofence/metrics.py` (기존) |

> 모두 scrape 시점에 DB를 조회하는 방식이라, 활성 zone/디바이스가 없으면
> series가 비는 것이 정상입니다.
