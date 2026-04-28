# 백오피스 v2 — 코어 마스터 4종 + FastAPI 동기화

3차 추가 작업 결과물. v1 (슈퍼관리자 채널) 위에 적용합니다.

## 포함 범위

### 신규 마스터 4종
| 메뉴 | 모델 | 기능 |
|---|---|---|
| **공통 코드 관리** | CodeGroup + Code | 7 그룹(DEVICE_TYPE/COMM_METHOD/GAS_TYPE/UNIT_CODE/EVENT_TYPE/NOTIF_CHANNEL/WORK_TYPE) + 40 코드. 그룹·코드 CRUD, bulk 사용/미사용 전환 |
| **위험 유형 관리** | RiskCategory + RiskType | 7 분류 + 15 유형. 반영 범위(실시간/이벤트/알림) 다중체크, 지도 표시 여부 토글 |
| **위험 기준 관리** | AlarmLevel | 4 단계(정상/주의/경고/위험) — 표시 색상·알림 강도·우선순위 |
| **임계치 기준 관리** | ThresholdCategory + Threshold | 4 분류(가스/전력/AI/공통) + 14 임계치. **운영 중 변경 가능, FastAPI 5초 동기화** |

### FastAPI 동기화 (이게 핵심)
- `fastapi_generator/django_loader.py` 에 `load_thresholds()` 추가
- `fastapi_generator/generators.py` GAS_THRESHOLDS 새 포맷으로 리팩터 + `apply_thresholds()` 함수 추가
- `fastapi_generator/scheduler.py` startup + 5초 reload 시 임계치 동기화

운영팀이 백오피스에서 CO 임계치를 25 → 35로 바꾸면 **5초 안에 데이터 생성기가 새 임계치로 동작**합니다. 이전엔 코드 재배포 필요했음.

### 데이터 무결성
- TH_GAS 시드값은 기존 `GAS_THRESHOLDS` 와 100% 일치 (CO 25/200, H2S 10/50, CO2 1000/5000, O2 under 18/16, O2 over 21.5/23.5, NO2 3/5, SO2 2/5, O3 0.05/0.1, NH3 25/50, VOC 0.5/2.0)
- 마이그레이션 후 시스템 동작이 변하지 않음 (값을 DB 로 옮기기만 함)
- O2 양방향(저산소 + 과산소) 모두 처리

## 적용 순서

1. v1 적용된 SenSa 프로젝트에 압축 해제 (덮어쓰기)
2. `python manage.py migrate` — backoffice.0004 + 0005 적용
3. `fastapi_generator/` 도 같이 덮어쓰기
4. Django 재시작 → FastAPI 재시작 → 백오피스 좌측 SNB → "기준정보 관리" 호버 → 4개 메뉴 활성화 확인

## 검증된 케이스

| 케이스 | 결과 |
|---|---|
| 4개 마스터 페이지 응답 | 200 (슈퍼관리자) / 403 (운영자) |
| 코드/유형/단계/임계치 등록 validation | 필드별 한글 에러 메시지 |
| 임계치 등록 — caution/danger 관계 (over/under) | "초과 일 때 위험값 > 주의값" 검증 |
| 시스템 시드 그룹/분류 삭제 시도 | 400 차단 |
| Django `/dashboard/api/thresholds/` | flat 14항목, categories 4개 |
| `generators.apply_thresholds()` | TH_GAS 10건 적용, TH_POWER 무시 |
| `identify_worst_gas` — 새 포맷 | CO/H2S 정규화 점수 비교, O2 양방향 정상 |
| 백오피스 CO 35로 변경 → API 재호출 → 30ppm 분류 | 정상으로 분류 (이전엔 위험) |
| `apply_thresholds(None)` (Django 미연결 시) | no-op, fallback 임계치 보존 |

## v2 trade-off (양해 필요)

- **공통 코드 → 다른 모델 FK 연결은 v3** — 현재는 자유 입력. 예: 임계치의 `unit` 은 UNIT_CODE 와 별개 free-text. 변경 자체는 단순 (Threshold.unit 을 FK 로) 인데, legacy 데이터 마이그레이션 비용이 있어 분리.
- **TH_POWER / TH_AI 적용은 v3** — 현재 임계치 동기화는 TH_GAS 만 generators 에 반영. 전력/AI 임계치는 등록은 가능하지만 실제 시스템 동작에는 미영향.
- **위험 유형 → 알람 발생 연동은 v3** — RiskType 등록은 가능하지만 alerts.Alarm 의 type 필드와 직접 연결은 미구현 (모델 join 만 추가하면 됨).
- **알림 단계 → alerts.Alarm.level 연동은 v3** — 같은 이유.

이 4가지는 v3 (5월 6일 이후 운영 단계) 에서 1-2일 내 가능.

## 파일 변경 요약 (총 21파일, +7,005 줄)

```
[backoffice 코어]
신규/대폭수정  backoffice/models.py             (+7 모델, ~280줄 추가)
대폭수정       backoffice/forms.py              (+8 폼 클래스, ~370줄 추가)
대폭수정       backoffice/views.py              (+22 뷰, ~430줄 추가)
대폭수정       backoffice/urls.py               (+22 URL 패턴)
신규           backoffice/migrations/0004_reference_masters.py
신규           backoffice/migrations/0005_seed_reference_masters.py

[설정]
수정           mysite/settings.py               (INTERNAL_API_ALLOWED_PATHS +1)
수정           mysite/urls.py                   (thresholds_for_fastapi import +1 path)

[화면]
수정           templates/backoffice/base.html   (SNB 확장 — 기준정보 관리 4개 하위메뉴)
신규           templates/backoffice/codes/manage.html
신규           templates/backoffice/risks/manage.html
신규           templates/backoffice/alarm_levels/list.html
신규           templates/backoffice/thresholds/manage.html
수정           static/css/backoffice/main.css   (sub-menu, master 2-패널, 색상 dot, applies pills, checkgroup)
신규           static/js/backoffice/codes.js
신규           static/js/backoffice/risks.js
신규           static/js/backoffice/alarm_levels.js
신규           static/js/backoffice/thresholds.js

[FastAPI 동기화 — 핵심]
수정           fastapi_generator/django_loader.py   (+ load_thresholds 함수)
대폭수정       fastapi_generator/generators.py      (GAS_THRESHOLDS 새 포맷, apply_thresholds, identify_worst_gas 리팩터)
수정           fastapi_generator/scheduler.py       (startup + 5초 reload 시 임계치 동기화)
```

## 다음 단계 우선순위 (v3 후보)

1. **알림 정책 / 발송 이력 관리** — 위험 기준 + 임계치 기준이 자리잡았으므로 위에 알림 정책 얹기 가능
2. **이벤트 이력 관리** — alerts.Alarm 조회/필터/CSV 다운로드
3. **메뉴 관리** — 역할별 메뉴 노출 (admin 역할에 부분 권한)
4. **공통 코드 ↔ 다른 모델 FK 연결** — UNIT_CODE → Threshold.unit 등
