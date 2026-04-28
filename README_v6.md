# 백오피스 v6 — Production 운영 안정화

v5 위에 적용. **데모 후 운영 단계 진입 직전**의 안정화 작업.

## 포함 범위 (6개 영역)

### 1. 감사 로그 (AuditLog)

백오피스 모든 액션 자동 추적. `post_save`/`post_delete` 시그널 + 미들웨어 thread-local 결합.

```python
# backoffice/audit.py 의 TRACKED_MODELS 에 등록된 모델은 자동 audit
# 등록·수정·삭제·로그인·로그아웃·로그인 실패 → AuditLog 1건씩 자동 생성
```

- **추적**: 누가(actor) / 언제(created_at) / 어떤 객체(target_app+model+pk+repr) / 어떻게(changes JSON) / 어디서(IP, request_path)
- **추적 모델**: 16개 (백오피스 13개 + accounts.User + devices.Device + geofence.GeoFence)
- **제외**: SensorData / WorkerLocation / NotificationLog (트래픽 폭증 방지)
- **시드 마이그레이션 audit 안 남김** (`get_current_request() is None` 체크)
- 페이지: `/backoffice/audit-logs/` — 필터(액션/모델/기간/키워드) + 페이지네이션 + 변경 내역 펼침
- SNB: 운영 데이터 관리 → "└ 감사 로그" 서브 메뉴

### 2. 외부 알림 게이트웨이 (Provider 패턴)

Stub-first 어댑터 — 운영 배포 시 settings 만 갈아끼우면 실제 SMTP/FCM/SMS 로 전환.

```python
# settings.py
NOTIFICATION_PROVIDERS = {
    'email':    'backoffice.notification_providers.email.EmailProvider',
    'sms':      'your_company.providers.AligoSmsProvider',  # 실제 어댑터로 교체
    'app':      'your_company.providers.FCMProvider',       # firebase-admin 등
    # 'realtime' 미설정 → ConsoleProvider 자동 fallback (개발 환경 안전)
}
```

- 4개 stub 구현체: console, email(send_mail), sms_stub, fcm_stub
- send_status 정확 갱신: `pending` → `sent`/`failed`/`skipped` (수신자 정보 없으면 skipped)
- Provider 1건 실패해도 다른 (사용자 × 채널) 발송 진행 (실패 격리)

### 3. 알림 비동기 큐

Celery 없이 `threading.Thread` + `queue.Queue` 기반.

```python
# settings.py
BACKOFFICE_ASYNC_NOTIFY = True   # default False (개발 환경 동기 유지)
```

- `apps.ready()` 에서 워커 자동 기동 (settings flag 조건)
- daemon thread 1개 — 직렬 처리 (DB 쓰기만 하므로 충분)
- 알람 → 시그널이 enqueue → 워커가 dispatch (요청은 즉시 응답, 발송 처리는 백그라운드)
- 검증: 5건 알람 큐 push → 워커가 처리 → 20건 NotificationLog 자동 생성

### 4. admin API 권한 분리

`@super_admin_required_api(menu_code='users', action='read')` 형식.

| action | 통과 조건 |
|---|---|
| `read` (GET) | super_admin OR (admin AND `is_visible`) |
| `write` (POST) | super_admin OR (admin AND `is_visible` AND `is_writable`) |

- **65개 API 데코레이터** 일괄 패치
- admin 시드 권한: `notices` 만 writable. 나머지는 read-only
- 검증: admin 이 position 등록 → 403, notice 등록 → 200

### 5. 장비 CSV upsert + DeviceHistory

```python
# CSV 업로드 모드
mode=create   # 기본 — 기존 device_id 는 skip (legacy)
mode=upsert   # v6 신규 — 기존 device_id 는 update + DeviceHistory 기록
```

- 모든 변경 (단건 등록·수정·CSV import) → DeviceHistory 자동 기록
- 변경 항목별 `[old, new]` JSON 저장
- 장비 화면에 [이력] 버튼 → 모달로 변경 이력 표시
- API: `GET /backoffice/api/devices/<id>/history/` — 최신 50건 반환

### 6. 지도 폴리곤 점 드래그 편집

지오펜스 폴리곤의 개별 점을 직접 드래그.

- 우측 목록에서 지오펜스 클릭 → 점 핸들 표시
- mousedown 으로 드래그 시작 → mousemove 시 폴리곤 즉시 갱신 + 캔버스 재렌더
- mouseup 시점에만 서버 PUT (mousemove 마다 PUT 안 함, 부하 방지)
- 드래그 안 한 단순 클릭은 자동 저장 발생 안 함
- 모달 편집은 [편집] 버튼 클릭 시만

## 적용 순서

1. v5 적용된 SenSa 위에 압축 해제
2. `python manage.py migrate` — backoffice.0010 적용 (AuditLog + DeviceHistory)
3. (선택) settings.py 에 비동기/외부 게이트웨이 활성화:

   ```python
   BACKOFFICE_ASYNC_NOTIFY = True
   NOTIFICATION_PROVIDERS = {
       'email': 'backoffice.notification_providers.email.EmailProvider',
       # ...
   }
   EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
   EMAIL_HOST = 'smtp.gmail.com'
   # ... SMTP 자격증명
   ```

4. Django 재시작 → 시그널·미들웨어·워커 자동 등록

## 검증된 케이스

| 케이스 | 결과 |
|---|---|
| Position 등록 → AuditLog 자동 1건 생성 (actor/IP/path 모두 캡처) | ✅ |
| MenuPermission 변경 → AuditLog | ✅ |
| 로그인 성공/실패 audit | ✅ 2건 자동 |
| 시드 마이그레이션 audit 제외 | ✅ (request 없으면 skip) |
| Provider 미설정 → console fallback | ✅ |
| settings.NOTIFICATION_PROVIDERS 적용 → 실제 어댑터 사용 | ✅ |
| 수신자 phone 없음 → `skipped` (실패 아님) | ✅ |
| 비동기 큐 — 5건 enqueue → 20건 NotificationLog 자동 생성 | ✅ |
| admin GET position → 200, POST position create → 403 (writable=False) | ✅ |
| admin POST notice create → 200 (writable=True) | ✅ |
| CSV upsert — GAS-001 좌표 변경 → updated=1, DeviceHistory 'csv_import' | ✅ |
| Device 단건 등록 → DeviceHistory 'create' + PIP 자동 매핑 | ✅ |
| 감사 로그 페이지 + 액션 필터 | ✅ |
| 폴리곤 점 드래그 (mousedown/move/up) → mouseup 시 자동 PUT | ✅ |

## v6 trade-off (양해)

- **외부 게이트웨이 실제 자격증명**: stub 만 제공. 운영 시 회사별 SMS gateway 어댑터 (Twilio / 알리고 / NHN Cloud 등) 직접 작성 필요. 인터페이스는 `(ok, err) = provider.send(recipient, msg, log)` 로 통일됨.
- **AuditLog 보관 정책 자동 적용**: cleanup_data 의 `audit_logs` target 은 모델 매핑 필요 (현재 _resolve_qs 에서 None 반환). 1줄 추가로 해결 가능.
- **알림 큐 영속성**: 프로세스 종료 시 in-flight 작업 손실. 영속 큐가 필요하면 Celery + Redis 또는 RabbitMQ.
- **벤더 락인 회피**: Provider 패턴이라 어댑터 교체 자유. 다만 settings 의 환경변수 주입은 운영팀 합의 필요.

## 파일 변경 요약 (총 24파일, +7,006 줄)

```
[v6 신규 인프라]
신규           backoffice/middleware.py                      ← request thread-local
신규           backoffice/audit.py                            ← TRACKED_MODELS, write_audit, login signals
신규           backoffice/notification_queue.py               ← threading 기반 워커
신규           backoffice/notification_providers/__init__.py  ← Provider 레지스트리
신규           backoffice/notification_providers/console.py
신규           backoffice/notification_providers/email.py
신규           backoffice/notification_providers/sms_stub.py
신규           backoffice/notification_providers/fcm_stub.py

[모델 + 마이그레이션]
대폭수정       backoffice/models.py                           ← AuditLog, DeviceHistory
신규           backoffice/migrations/0010_audit_and_device_history.py

[시그널/디스패처/권한]
대폭수정       backoffice/notification_dispatcher.py          ← Provider 호출 + send_status 갱신
대폭수정       backoffice/signals.py                          ← settings flag 보고 동기/비동기 분기
대폭수정       backoffice/permissions.py                      ← API 데코레이터 menu_code+action
수정           backoffice/apps.py                             ← audit signals + 워커 기동

[뷰/URL/폼]
대폭수정       backoffice/views.py                            ← 65 API menu_code 부착, audit_log_list, device_history_api, csv upsert
수정           backoffice/urls.py                             ← +2 URL
수정           backoffice/forms.py                            ← Device 변경 추적

[설정]
수정           mysite/settings.py                             ← AuditContextMiddleware 등록

[화면]
수정           templates/backoffice/base.html                 ← 감사 로그 sub-menu
신규           templates/backoffice/audit/log_list.html
수정           templates/backoffice/devices/list.html         ← CSV upsert 드롭다운, history 모달
수정           templates/backoffice/maps/edit.html            ← 점 드래그 안내
수정           static/js/backoffice/devices.js                ← upsert + history
수정           static/js/backoffice/maps.js                   ← vertex drag mousedown/move/up
```

## 누적 결과 (v1 ~ v6)

- **약 34,000줄, 19개 화면, 8개 1Depth 메뉴 + Production 인프라**
- 시드 → 자동화 → 권한 → 감사 → 외부 게이트웨이까지 풀스택
- 모든 변경 추적 가능, 운영팀이 백오피스에서 시스템 전 영역 컨트롤 + 감사 추적

| 카테고리 | 가능한 것 |
|---|---|
| 마스터 관리 | 사용자/조직/직위/코드/위험분류·기준/임계치/장비/지오펜스/공지 |
| 운영 자동화 | 알람→알림 자동 발송 / 데이터 정리 batch / 좌표→지오펜스 자동 매핑 |
| 권한 제어 | super_admin / admin (메뉴별 read/write) / operator |
| 데이터 입출 | CSV 업로드 (장비, create/upsert) / CSV 다운로드 (이벤트) |
| 시스템 통합 | FastAPI 5초 임계치 동기화 + post_save 시그널 |
| **운영 안정화** | **AuditLog / 외부 Provider / 비동기 큐 / DeviceHistory / 폴리곤 드래그** |

## 운영 진입 체크리스트

- [x] 데이터 마스터 등록 가능
- [x] 임계치 운영 중 변경 (FastAPI 동기화)
- [x] 알림 정책 + 자동 발송
- [x] 감사 로그 추적
- [x] 권한 분리 (super/admin/operator)
- [x] 데이터 정리 batch
- [x] CSV 일괄 등록 + 변경 이력
- [x] 외부 게이트웨이 어댑터 인터페이스
- [x] 비동기 큐 (알람 폭증 대비)
- [ ] 실제 SMS/FCM 자격증명 주입 (회사별 결정)
- [ ] cron 등록 (`cleanup_data`)
- [ ] 모니터링/로깅 인프라 (Sentry 등)
