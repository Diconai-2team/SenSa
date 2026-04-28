# 백오피스 v5 — 운영 인프라 (워커, batch, 자동화, 권한 활성화)

v4 위에 적용. **백오피스 등록·조회 시스템에서 → 실제 운영 가능한 시스템으로 전환**.

## 포함 범위

### 1. 알림 발송 워커 (Celery 없이)

`alerts.Alarm.post_save` 시그널 → 자동으로 매칭 정책 평가 → `NotificationLog` 생성.

```python
# 동작 흐름
Alarm 생성 (FastAPI/Django 어디서든)
  └→ post_save 시그널 발화
     └→ backoffice.notification_dispatcher.dispatch_for_alarm()
        ├→ alarm.alarm_type + sensor_type → RiskCategory.code 매핑
        ├→ alarm.alarm_level → AlarmLevel.priority 비교
        ├→ 조건 맞는 NotificationPolicy 모두 평가
        ├→ recipients_csv 토큰 펼치기 (all_users / leaders / group:N / role:X)
        └→ 각 (사용자 × 채널) 마다 NotificationLog 1건 작성
```

**검증된 결과**: 가스 위험 알람 1건 → 14건 NotificationLog 자동 생성 (3개 정책 × 평균 4-5명).

### 2. 데이터 정리 batch

`python manage.py cleanup_data` — DataRetentionPolicy 따라 누적 데이터 삭제.

```bash
# cron 등록 권장
0 3 * * *  cd /your/SenSa && python manage.py cleanup_data >> /var/log/cleanup.log

# 안전 확인 (dry-run)
python manage.py cleanup_data --dry-run

# 단일 target 만
python manage.py cleanup_data --target alarms
```

UI 측 "지금 실행" 버튼도 추가됨 — `/backoffice/operations/retention/` 에서 정책 행마다 클릭.

### 3. 장비 좌표 → 지오펜스 자동 매핑

`shapely` 미설치 환경에서도 동작하는 ray casting 알고리즘 (`backoffice/geo_utils.py`).

- **단건 등록 시**: DeviceForm.save() 안에서 자동 매핑 (geofence 미지정 시)
- **일괄 매핑**: `/backoffice/devices/` 화면 "📍 좌표→지오펜스 자동 매핑" 버튼
- **CSV 업로드 시**: 등록되는 모든 장비에 자동 매핑 적용

우선순위: `danger > restricted > caution`. 여러 폴리곤 안에 있으면 가장 위험한 zone 선택.

### 4. 장비 CSV 일괄 등록

`/backoffice/devices/` 화면 "📁 CSV 업로드" 버튼.

```csv
device_id,device_name,sensor_type,x,y,is_active,last_value_unit
GAS-100,1공장 동측 가스,gas,250,300,true,ppm
POW-100,1공장 배전반 3,power,950,400,true,A
```

- UTF-8 BOM 허용 (Excel 호환)
- 5MB 제한
- 중복 device_id → 건너뜀
- 라인별 에러 리포트

### 5. admin 사용자 백오피스 진입 + SNB 분기

**가장 큰 변화**: 그동안 super_admin 만 백오피스 들어왔지만, v5부터 admin 도 진입 가능.

- 데코레이터 변경: `@super_admin_required(menu_code='users')` 형식
- `MenuPermission` 에 `is_visible=True` 등록된 메뉴만 admin 접근 가능
- `backoffice/context_processors.py` 가 `visible_menus` 컨텍스트 주입 → SNB 가 자동 분기

**시드 권한** (`backoffice/migrations/0007`):

| 메뉴 | admin 권한 |
|---|---|
| 계정/권한 관리 | ✅ visible |
| 메뉴 관리 | ❌ |
| 설비/장비 관리 | ✅ visible |
| 지도 편집 관리 | ❌ |
| 기준정보 관리 | ✅ visible |
| 운영 데이터 관리 | ✅ visible |
| 공지사항 관리 | ✅ visible + writable |
| 알림/이벤트 관리 | ✅ visible |

→ super_admin 이 `/backoffice/menus/` 에서 운영 중 변경 가능.

### 6. 공지 → 사용자 알림 발송

공지 등록 모달에 "등록과 동시에 사용자에게 알림 발송" 체크박스 추가.
체크하면 활성 사용자 전원에게 (`app, realtime` 채널 기본) NotificationLog 작성.

또한 기존 공지에 대해 수동 발송 API: `POST /backoffice/api/notices/<id>/dispatch/`.

## 적용 순서

1. v4 적용된 SenSa 위에 압축 해제
2. `python manage.py check` (마이그레이션 신규 없음)
3. Django 재시작 → 시그널 핸들러 자동 등록
4. (선택) admin 계정 생성하여 admin SNB 분기 확인:

    ```python
    python manage.py shell
    from accounts.models import User
    U = User.objects.create_user(
        username='admin01', password='Admin1234!',
        first_name='관리자', email='admin@co.kr', role='admin',
    )
    ```

5. (선택) cron 등록하여 매일 새벽 데이터 정리:

    ```cron
    0 3 * * *  cd /your/SenSa && /your/venv/bin/python manage.py cleanup_data
    ```

## 검증된 케이스

| 케이스 | 결과 |
|---|---|
| 16개 백오피스 페이지 (super_admin) | 100% 200 |
| admin 권한 매트릭스 (시드 기준) | 14개 가능 / 2개 차단 (menus, maps) |
| operator 백오피스 차단 | 16/16 모두 403 |
| 알람 1건 생성 → 자동 알림 | 14건 NotificationLog 생성 |
| 알림 정책 매칭 (RISK_GAS + DANGER priority) | POLICY_GAS_DANGER + POLICY_GAS_CAUTION 발화 |
| 수신자 토큰 (all_users / leaders / role:X) | 정상 펼침 |
| `cleanup_data --dry-run` | 모든 target 0건 (시드 데이터 모두 1주 이내) |
| PIP `(500,500)` in `[[400,300],[800,300],[800,600],[400,600]]` | True ✅ |
| PIP `(100,100)` in 위 폴리곤 | False ✅ |
| `device_auto_map_geofence_api` | 4건 매핑 (시드 5장비 중 폴리곤 안 4개) |
| CSV 업로드 (BOM 포함) | created=1 |
| 공지 dispatch | 4건 (활성 사용자 4명 × 1채널) |
| admin SNB 표시 | 권한 있는 6개 메뉴만 (menus, maps 숨김) |

## v5 trade-off (양해)

- **알림 실제 발송 (FCM/SMTP/SMS gateway)**: NotificationLog 만 작성. 외부 게이트웨이 연동은 v6 — 정책 트리거 + 발송 추적 인프라가 자리잡았으니 1-2일.
- **admin 의 API 호출 권한**: 페이지 접근만 분기. API (POST /create/, /update/) 는 여전히 super_admin only. → admin 이 페이지를 보고 수정/등록 시도하면 403. v6 에서 `is_writable` 까지 반영해 분기 필요.
- **장비 CSV 업로드 — 수정/삭제는 미지원**: 신규 등록만. v6에서 `mode=upsert` 옵션 추가 가능.
- **알림 발송 큐**: 동기 방식. 알람 폭증 시 트랜잭션이 길어질 수 있음. 운영 부하 측정 후 v6에서 별도 워커로 분리.
- **지도 편집 — 폴리곤 점 드래그 편집**: 여전히 v6.

## 파일 변경 요약 (총 20파일, +5,538 줄)

```
[v5 신규 인프라]
신규           backoffice/notification_dispatcher.py        ← 알림 디스패처
신규           backoffice/signals.py                         ← post_save 핸들러
신규           backoffice/geo_utils.py                       ← PIP
신규           backoffice/context_processors.py              ← SNB 권한 분기
신규           backoffice/management/__init__.py
신규           backoffice/management/commands/__init__.py
신규           backoffice/management/commands/cleanup_data.py

[수정]
수정           backoffice/apps.py                            ← signals import
대폭수정       backoffice/permissions.py                     ← admin 진입 + menu_code 데코레이터
대폭수정       backoffice/views.py                           ← 16개 페이지 menu_code 부착, 4개 신규 API
수정           backoffice/urls.py                            ← 4개 신규 URL
수정           backoffice/forms.py                           ← Device PIP 자동 매핑
수정           accounts/views.py                             ← admin 도 백오피스 리다이렉트
수정           mysite/settings.py                            ← context_processors 등록

[화면]
수정           templates/backoffice/base.html                ← SNB visible_menus 분기
수정           templates/backoffice/devices/list.html        ← CSV/auto-map 버튼
수정           templates/backoffice/operations/retention_list.html  ← '지금 실행'
수정           templates/backoffice/notices/list.html        ← 발송 옵션 체크박스
수정           static/js/backoffice/devices.js               ← CSV/auto-map 핸들러
수정           static/js/backoffice/notices.js               ← send_notify
```

## 누적 결과 (v1 + v2 + v3 + v4 + v5)

- **약 27,000줄, 18개 화면, 8개 1Depth 메뉴 100% + 운영 인프라**
- 모든 화면 + 시그널 + batch + 권한 분기 자동화 검증 완료

| 카테고리 | 가능한 것 |
|---|---|
| 마스터 관리 | 사용자/조직/직위/코드/위험분류·기준/임계치/장비/지오펜스/공지 |
| 운영 자동화 | **알람→알림 자동 발송 / 데이터 정리 batch / 좌표→지오펜스 자동 매핑** |
| 권한 제어 | super_admin 무제한 + admin 메뉴별 권한 + operator 차단 |
| 데이터 입출 | **CSV 업로드 (장비) / CSV 다운로드 (이벤트)** |
| 시스템 통합 | FastAPI 5초 임계치 동기화 + `post_save` 시그널 |
