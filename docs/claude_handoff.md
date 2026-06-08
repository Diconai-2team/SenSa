# SenSa AI 시스템 Claude Hand-off 문서

> 작성일: 2026-06-05
> 브랜치: `integrate/shj-teamwork`
> 작업자: shj
> 목적: AI 과발화 디버깅 및 수정 작업 인수인계

---

## 현재 시스템 상태

```
sensa_django          Up (healthy) ✅
sensa_celery          Up ✅  (5분 전 재시작)
sensa_celery_scenario Up ✅
sensa_generator       Up ✅  (14분 전 재시작)
sensa_postgres        Up (healthy) ✅
sensa_redis           Up ✅
sensa_prometheus      Up ✅
sensa_grafana         Up ✅
```

---

## 이번 세션에서 완료된 작업

### ✅ 1. predicted_ticks 동적화 (arima_forecaster.py + devices/views.py)

**문제**: ARIMA가 "N틱 후 임계치 초과" 예측을 생성할 때 `predicted_ticks`가
항상 10으로 고착되어 실제 임박도를 반영하지 못함.

**수정 내용**:
- `SenSa/ml_engine/arima_forecaster.py`: `forecast()` 반환값에 `first_exceed_tick` 추가
  - 예측 배열(preds)에서 **처음으로 임계치를 초과하는 틱 번호**를 계산
  - O2(lower_is_worse) 양방향 처리 분리
  - 초과 없으면 `None` → views.py에서 10틱 fallback
- `SenSa/devices/views.py`: `predicted_ticks` 저장 로직 수정
  - `first_exceed_tick` 기반 동적 산출
  - `expires_at = max(predicted_ticks * 9, 45)초`

**검증**:
```
수정 전: predicted_ticks = 10틱 (100% 고착)
수정 후: 1틱: 29건 / 10틱: 119건 (다양화 확인)
predicted_ticks=1 케이스 8건 → 전부 result=success
```

---

### ✅ 2. arima_cycle 비활성화 (IF 학습 오염 방지)

**문제**: `arima_cycle`이 sensor_02 CO를 6분 주기로 0→444ppm까지 자동 ON/OFF.
IF 모델이 이를 "정상 분포"로 학습 → 정상 데이터의 **54.1%를 이상으로 판정**
(이론치 3%의 **18배 과발화**).

**수정 내용**:
- `fastapi_generator/config.py`: `ARIMA_CYCLE_ENABLED` 환경변수 추가
- `fastapi_generator/scheduler.py`: `tick()` 진입부에 `ARIMA_CYCLE_ENABLED` 체크 추가
- `fastapi_generator/.env`: `ARIMA_CYCLE_ENABLED=false` 설정

```python
# scheduler.py 변경 핵심
def tick(self, tick: int, scenario_state) -> None:
    if not ARIMA_CYCLE_ENABLED:   # ← 추가된 줄
        return
    ...
```

**주의**: arima_cycle을 끄면 sensor_02 CO의 상승 패턴이 ARIMA 학습 데이터에서
줄어들어 `ai_predictive_*` 알람이 CO 위주로 감소할 수 있음.
(다른 가스 예측은 영향 없음)

---

### ✅ 3. AI 알람 쿨다운 상향 (devices/views.py)

**문제**: 쿨다운이 `sensor_type=metric` 단위(가스 종류별)로 동작해
9개 가스 채널이 각자 30초 쿨다운 → 실제 평균 **8.2초마다** 알람 발화.

**수정 내용**:
```python
# SenSa/devices/views.py 83-84번째 줄
_GAS_COOLDOWN_SEC  = 120   # 30 → 120 (가스 AI 알람 쿨다운)
_BASE_COOLDOWN_SEC = 60    # 10 → 60  (전력·에스컬레이션 쿨다운)
```

**예상 효과**: AI 알람 총량 기존 대비 약 1/4 수준으로 감소.

---

### ✅ 4. sensor_02 IF 모델 초기화

**문제**: 오염된 데이터로 39,851회 학습된 sensor_02 IF 모델이
Celery 프로세스 메모리에 잔존.

**조치**:
- Django shell에서 `_models`의 sensor_02 9개 키 제거
- `if_models.pkl` 갱신 (sensor_02 제외 상태로 저장)
- Celery 재시작 → 깨끗한 pkl 로드

**현재 상태**:
```
전체 IF 모델: 66개 (sensor_02가 재학습 완료된 상태)
sensor_02: 9개 (재학습됨)
```

---

## 🚧 남은 작업 / 확인 필요 사항

### 1. sensor_02 IF 재학습 품질 검증 (최우선)

재학습 후 offset_이 오염 전 수준(-0.63 내외)으로 돌아왔는지 확인 필요.

```python
# Celery에서 확인
docker exec sensa_celery python -c "
import django, os; os.environ['DJANGO_SETTINGS_MODULE']='mysite.settings'; django.setup()
from ml_engine.isolation_forest import _models
for k,v in sorted(_models.items()):
    if k.startswith('sensor_02'):
        m = v.get('model')
        print(f'{k}: offset={m.offset_:.4f} trained={v.get(\"trained_call_count\")}')
"
```

**오염 전 기준값**: offset ≈ -0.63 (범위 -0.727 ~ -0.569)
**오염 시 sensor_02:co**: offset = -0.5940 (낮아서 정상 범위가 넓음)

### 2. 과발화 개선 수치 재측정

쿨다운 + arima_cycle 비활성화 + IF 재학습 후 1시간 대기 후 측정.

```python
docker exec sensa_django python manage.py shell -c "
from alerts.models import Alarm
from devices.models import SensorData
from django.utils import timezone; from datetime import timedelta

t1h = timezone.now()-timedelta(hours=1)
total_sd = SensorData.objects.filter(timestamp__gt=t1h).count()
total_ai = Alarm.objects.filter(is_ai=True, created_at__gt=t1h).count()
total_th = SensorData.objects.filter(timestamp__gt=t1h, status__in=['caution','danger']).count()
print(f'실제 이상 비율: {total_th/total_sd*100:.1f}%')
print(f'AI 발화율: {total_ai/total_sd*100:.1f}%')
print(f'목표: AI 발화율 ≈ 실제 이상 비율의 2~3배 이내')
"
```

**목표 수치**: AI 발화율 6~15% (현재 31.5% → 개선 기대)

### 3. TICK_INTERVAL=2.0 적용 (선택)

팀원이 `.env`에 `TICK_INTERVAL=2.0`으로 변경했으나 **컨테이너에 미반영** 상태.
현재 실제 틱 간격: ~2.6초 (네트워크 지연으로 1.0이어도 2초대).

적용하려면:
```bash
# fastapi_generator/.env 에서 확인 후
docker compose up -d --build generator
```

**효과**: Celery AI task 도착 속도 절반 → backlog 감소.
**주의**: 탐지 반응 속도 2배 느려짐.

### 4. AI 성능 보고서 재측정

`/root/SenSa/docs/ai_performance_report.md` 파일이 있음.
과발화 수정 후 1~2시간 뒤 데이터로 재측정 권장.

---

## 핵심 파일 위치

| 파일 | 역할 | 최근 수정 |
|---|---|---|
| `SenSa/devices/views.py` | AI 알람 쿨다운, AIPrediction 저장 | ✅ 이번 세션 |
| `SenSa/ml_engine/arima_forecaster.py` | ARIMA 예측, first_exceed_tick | ✅ 이번 세션 |
| `SenSa/ml_engine/isolation_forest.py` | IF 모델 학습/예측 | 미수정 |
| `SenSa/ml_engine/pipeline.py` | 탐지기 앙상블 실행 | 미수정 |
| `SenSa/ml_engine/apps.py` | 재시작 시 모델 복원 | 미수정 |
| `fastapi_generator/config.py` | ARIMA_CYCLE_ENABLED 상수 | ✅ 이번 세션 |
| `fastapi_generator/scheduler.py` | arima_cycle 비활성화 | ✅ 이번 세션 |
| `fastapi_generator/.env` | ARIMA_CYCLE_ENABLED=false | ✅ 이번 세션 |
| `docker-compose.yml` | 큐 분리(celery/scenario), DB_ENGINE | 이전 세션 |
| `SenSa/mysite/settings.py` | CELERY_TASK_ROUTES | 이전 세션 |

---

## 과발화 원인 요약 (참고)

| 원인 | 기여도 | 조치 상태 |
|---|---|---|
| arima_cycle → IF 학습 오염 | **가장 큼** (18배 과발화) | ✅ 비활성화 완료 |
| 쿨다운 채널별 분산 (9가스 × 30초) | **큼** | ✅ 120초로 상향 완료 |
| contamination 미스매치 (3% vs 실제 6%) | 보통 | 🔄 IF 재학습으로 자동 수렴 예정 |
| CUSUM 과발화 | 작음 | 300초 쿨다운으로 제어 중 |

---

## Discord Critical 알림 구현 가이드

> 이 섹션은 Discord 알림 코드가 **전혀 없는 상태**에서 구현하는 방법을 설명합니다.
> 현재 프로젝트에는 이미 구현되어 있으므로 "동작 방식 이해" 또는 "다른 프로젝트 이식" 용도로 참고하세요.

---

### 배경 — 이전에 논의했던 고민들

**Q. Grafana Alert로 Discord에 보낼 수 없나?**
→ Grafana는 Prometheus 메트릭(숫자) 기반이라 "zone이 critical로 승격됐다"는
비즈니스 이벤트를 실시간으로 잡기 어렵습니다. Django 앱 내부에서 직접 발송하는 게 정확합니다.

**Q. Discord 알림이 오려면 작업자가 critical 존에 들어가야 하나?**
→ 작업자 "진입"이 기준이 아닙니다. **이상 신호를 보내는 이웃 센서 수**가 기준입니다.
동적 zone 반경 내 센서 중 이상 감지된 센서가 3개 이상이면 critical 승격 → Discord 발송.

**Q. 정적 zone이 critical이면 Discord가 나가나?**
→ ❌ 안 나갑니다. Discord는 **동적 zone**이 critical로 **승격되는 순간** 단 1회만 발송됩니다.
정적 zone은 tier 승격 로직 자체를 타지 않습니다(`is_dynamic=False` 체크로 즉시 return).

---

### 구현 단계 (처음부터 구현 시)

#### Step 1. Webhook 발송 모듈 생성
**파일**: `alerts/notifiers.py` (신규 생성)

```python
import os, logging, requests
logger = logging.getLogger('alerts.notifiers')

DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')
DRY_RUN = os.environ.get('SENSA_NOTIFY_DRY_RUN', 'false').lower() == 'true'

def is_configured():
    return bool(DISCORD_WEBHOOK_URL or DRY_RUN)

def send_discord(text: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={'content': text}, timeout=5)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f'Discord 발송 실패: {e}')
        return False

def notify_external(title: str, message: str, severity: str = 'critical') -> dict:
    EMOJI = {'critical': '🔴', 'danger': '🚨', 'caution': '⚠️'}
    emoji = EMOJI.get(severity, '🔔')
    text = f"{emoji} **[SenSa] {title}**\n{message}"

    if DRY_RUN:
        logger.info(f'[DRY-RUN] {text}')
        return {'discord': False, 'dry_run': True, 'skipped': False}

    if not is_configured():
        return {'discord': False, 'dry_run': False, 'skipped': True}

    ok = send_discord(text)
    return {'discord': ok, 'dry_run': False, 'skipped': False}
```

#### Step 2. Celery 비동기 Task 생성
**파일**: `alerts/tasks.py` (신규 생성 또는 기존 파일에 추가)

```python
from celery import shared_task
from alerts.notifiers import notify_external

@shared_task(
    name='alerts.tasks.send_external_notification',
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 5},
    retry_backoff=True,
)
def send_external_notification_task(title, message, severity='critical', alarm_id=None):
    result = notify_external(title, message, severity)
    return result
```

#### Step 3. Zone critical 승격 시 Task 호출
**파일**: `geofence/events.py` — zone 라이프사이클 이벤트 발행 함수에 추가

```python
def emit(zone, event_type, **kwargs):
    # ... 기존 ZoneEvent DB 저장, WebSocket 푸시 코드 ...

    # critical 승격 시에만 Discord 발송
    if event_type == 'upgraded_to_critical':
        _notify_external_critical(zone, kwargs)

def _notify_external_critical(zone, kwargs):
    try:
        from alerts.notifiers import is_configured
        if not is_configured():
            return

        from alerts.tasks import send_external_notification_task

        title = f"Zone 긴급 승격 — {zone.name}"
        message = (
            f"가스: {zone.gas_type.upper() if zone.gas_type else '?'}\n"
            f"승격: {kwargs.get('from_tier', '?')} → critical\n"
            f"확인 센서: {zone.confirmed_devices.count()}개\n"
            f"반경: {zone.current_radius_px:.0f}px"
        )

        send_external_notification_task.delay(
            title=title,
            message=message,
            severity='critical',
        )
    except Exception as e:
        logger.warning(f'외부 알림 큐잉 실패: {e}')  # 라이프사이클은 영향 없어야 함
```

#### Step 4. Celery 큐 라우팅 설정
**파일**: `mysite/settings.py`

```python
CELERY_TASK_ROUTES = {
    # Discord 알림은 AI 파이프라인 큐가 아닌 별도 scenario 큐로
    # (AI backlog가 쌓여도 Discord 발송이 막히지 않도록)
    'alerts.tasks.send_external_notification': {'queue': 'scenario'},
}
```

#### Step 5. 환경변수 설정
**파일**: `/root/SenSa/.env` (루트 — docker-compose가 env_file로 주입)

```bash
# Discord webhook URL (Discord 서버 → 채널 설정 → 웹훅 → URL 복사)
DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN

# 테스트 시 실제 발송 없이 로그만 출력하려면:
SENSA_NOTIFY_DRY_RUN=true
```

#### Step 6. critical 승격 조건 이해 (언제 Discord가 오나)

```
동적 zone 생성 (trigger: ttm_anomaly / ttm_forecast / threshold)
    ↓
tick_zones (30초 주기 Celery beat) → check_tier_upgrade() 호출
    ↓
zone 반경 내 이웃 센서 중 이상 감지 센서 수 확인
    ↓
confirmed_devices 수 >= 1  →  tentative → confirmed
confirmed_devices 수 >= 3  →  confirmed → critical  →  🔴 Discord 발송
```

**핵심 상수** (`geofence/zone_lifecycle.py`):
```python
MIN_CONFIRMING_FOR_CONFIRMED = 1  # tentative → confirmed
MIN_CONFIRMING_FOR_CRITICAL  = 3  # confirmed → critical (Discord 트리거)
```

**주의**: `trigger_source`가 `'scenario_op_*'`로 시작하는 시나리오 zone은
tier 자동 승격에서 제외됩니다 (TTL 시연 목적 보호).

#### Step 7. 동작 확인 방법

```bash
# 1. 직접 테스트 (즉시 Discord 발송)
docker exec sensa_django python manage.py shell -c "
from alerts.notifiers import notify_external
result = notify_external('테스트', '수동 테스트 메시지', severity='critical')
print(result)
"

# 2. Celery task 경유 테스트 (실제 운영 경로)
docker exec sensa_django python manage.py shell -c "
from alerts.tasks import send_external_notification_task
send_external_notification_task.delay('테스트 제목', '테스트 내용', 'critical')
print('큐잉 완료 — Celery 워커가 발송')
"

# 3. Celery scenario 워커 로그 확인
docker logs sensa_celery_scenario 2>&1 | grep -i "discord\|notify\|외부"

# 4. DRY_RUN 모드로 안전하게 흐름만 테스트
# .env에 SENSA_NOTIFY_DRY_RUN=true 추가 후 재빌드
```

#### Step 8. 재빌드 (환경변수 변경 시)

```bash
cd /root/SenSa
docker compose up -d --build django celery celery_scenario
```

---

### 이전 대화에서 논의된 고민/질문 정리

**Q1. "Grafana에서 Discord를 통해 critical 발생 시 외부로 위험 알람을 보내고 싶다"**
→ Grafana Alert보다 **Django 앱 내부에서 직접 Discord webhook POST** 하는 방식으로 구현.
이유: Grafana는 Prometheus 메트릭 기반이라 zone 승격 같은 비즈니스 이벤트를 실시간으로
잡기 어렵고, Django가 이미 zone 라이프사이클을 관리하므로 `events.py`에서 직접 큐잉하는 게 정확함.

**Q2. "Discord로 알람이 오려면 시나리오와 관계없이 작업자가 critical 존에 들어가야 오는 거 아니야?"**
→ 반은 맞고 반은 틀림.
- **동적 zone**은 `tentative → confirmed → critical` 자동 승격 구조라 작업자 수가 기준.
  `confirmed_devices`에 충분한 센서/작업자가 들어오면 자동 승격 → Discord 발송.
- 즉 작업자가 zone에 **진입**하는 게 아니라, zone 내 **이상 확인 센서 수**가 기준.

**Q3. "정적 zone이 critical인 건 Discord 보내는 거랑 상관없다는 말이네"**
→ 정확함. 두 가지 이유:
1. Discord는 zone이 critical **"이다"** 가 아니라 critical로 **"승격되는 순간"** (`upgraded_to_critical` 이벤트) 단 1회 발송.
2. 정적 zone(`is_dynamic=False`)은 tier 승격 로직 자체를 타지 않음 (`zone_lifecycle.py`에서 `is_dynamic` 체크 후 즉시 return).

**결론**: Discord 알림은 **동적 zone이 critical로 승격되는 순간**에만 발송.
정적 zone, 단순 AI 알람(ai_ml_anomaly 등), threshold 알람은 Discord 대상이 아님.

---

### 현재 상태: ✅ 이미 구현 완료 — 추가 코딩 불필요

> Discord 알림은 **이미 작동 중**입니다. 새로 구현할 것은 없고,
> 아래 내용을 읽고 동작 방식과 테스트 방법만 파악하면 됩니다.

### 전체 구현 흐름
```
zone이 critical 승격
  → geofence/events.py: _notify_external_critical()
    → alerts/tasks.py: send_external_notification_task.delay()  ← Celery scenario 큐
      → alerts/notifiers.py: notify_external() → send_discord()
        → Discord webhook POST
```

**발송 조건**: `upgraded_to_critical` 이벤트 발생 시에만 (소음 방지).
zone이 tentative → confirmed → **critical** 로 승격될 때 1회 발송.

**관련 파일**:
| 파일 | 역할 |
|---|---|
| `geofence/events.py:72` | critical 승격 시 알림 큐잉 트리거 |
| `geofence/events.py:85` | `_notify_external_critical()` 함수 |
| `alerts/tasks.py` | `send_external_notification_task` Celery task |
| `alerts/notifiers.py` | Discord/Slack webhook 실제 발송 |

**환경변수 설정 상태**:
```bash
DISCORD_WEBHOOK_URL=설정됨 (실제 URL 존재)  ← .env 또는 docker-compose에 있음
SENSA_NOTIFY_DRY_RUN=미설정 (실제 발송 활성)
```

**큐 라우팅**: `send_external_notification_task`는 `scenario` 큐로 라우팅됨
(`mysite/settings.py` CELERY_TASK_ROUTES 참고).
`sensa_celery_scenario` 워커가 처리.

**테스트 방법**:
```python
# Django shell에서 직접 테스트
docker exec sensa_django python manage.py shell -c "
from alerts.notifiers import notify_external
result = notify_external('테스트 알림', '수동 테스트 메시지', severity='critical')
print(result)
"
```

---

## 브랜치 아키텍처 요약 (팀원 참고)

**integrate/shj-teamwork가 AI_test_shj보다 안정적인 이유**:
- AI 파이프라인 (IF/ARIMA/CUSUM 등)이 **Celery 워커 프로세스**에서 실행
- Django POST는 `task.delay()` 큐잉만 하고 즉시 반환 → **GIL 점유 없음**
- AI_test_shj는 Django 요청 스레드에서 직접 실행 → GIL 점유 → Django 다운 반복

**Celery 부하 주의**:
- concurrency=1, AI task 평균 0.7~1.5초 → POST 속도 따라잡기 어려움
- TICK_INTERVAL=2.0 적용 시 backlog 절반으로 감소 예상
- 큐: `celery`(AI 파이프라인) / `scenario`(시나리오·알림)로 분리됨

---

## Claude에게 전달할 컨텍스트 (새 대화 시작 시 붙여넣기)

```
브랜치: integrate/shj-teamwork
작업 상태:
- predicted_ticks 동적화 완료 (arima_forecaster.py + views.py)
- arima_cycle 비활성화 완료 (ARIMA_CYCLE_ENABLED=false)
- AI 쿨다운 30→120초 완료 (views.py)
- sensor_02 IF 모델 초기화 + Celery 재시작 완료

다음 할 일:
1. sensor_02 IF 재학습 품질 확인 (offset_ 값)
2. AI 발화율 재측정 (목표: 31.5% → 6~15%)
3. (선택) TICK_INTERVAL=2.0 generator 재빌드 적용
4. AI 성능 보고서 재측정 및 docs/ai_performance_report.md 갱신

핵심 확인 명령:
docker exec sensa_celery python -c "
import django, os; os.environ['DJANGO_SETTINGS_MODULE']='mysite.settings'; django.setup()
from ml_engine.isolation_forest import _models
for k,v in sorted(_models.items()):
    if k.startswith('sensor_02'):
        m=v.get('model'); print(f'{k}: offset={m.offset_:.4f} trained={v.get(\"trained_call_count\")}')
"
```
