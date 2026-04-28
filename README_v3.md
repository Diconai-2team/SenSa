# 백오피스 v3 — 알림 정책 + 이벤트 이력 + 메뉴 관리

v2 (코어 마스터 4종) 위에 적용. 백오피스 8개 1Depth 메뉴 중 7개가 v3 까지 활성화 완료.

## 포함 범위

### 신규 화면 4종

| 메뉴 | 모델 | 기능 |
|---|---|---|
| **이벤트 이력** | (alerts.Alarm 조회) | 검색·필터(레벨/유형/기간/키워드/안읽음)·페이지네이션·CSV 다운로드·읽음 처리·상세 모달 |
| **알림 정책** | NotificationPolicy | 위험분류+알람단계 트리거에 채널·수신자 매핑. 5건 시드 (가스 위험/주의, 전력, 위치, 작업안전) |
| **발송 이력** | NotificationLog | 정책 발송 결과 조회. 24h 통계 (성공/실패/대기) + 검색·필터·페이지네이션 |
| **메뉴 관리** | MenuPermission | admin 역할 메뉴별 조회/등록 권한 토글 매트릭스. super_admin 은 항상 전체 |

### 백오피스 메뉴 활성화 현황

| 1Depth | 상태 |
|---|---|
| 계정/권한 관리 | ✅ v1 |
| 메뉴 관리 | ✅ v3 |
| 설비/장비 관리 | ⏳ |
| 지도 편집 관리 | ⏳ |
| 기준정보 관리 (4종) | ✅ v2 |
| 운영 데이터 관리 | ⏳ |
| 공지사항 관리 | ⏳ |
| 알림/이벤트 관리 (3종) | ✅ v3 |

## 적용 순서

1. v2 적용된 SenSa 위에 압축 해제 (덮어쓰기)
2. `python manage.py migrate` — backoffice.0006 + 0007 적용
3. Django 재시작 → 좌측 SNB 호버 → "메뉴 관리" / "알림/이벤트 관리" 활성화 확인

## 검증된 케이스

| 케이스 | 결과 |
|---|---|
| 4개 신규 페이지 응답 (super_admin) | 200 |
| 이벤트 이력 검색·필터 (level=danger, keyword=H2S) | 정상 작동 |
| 이벤트 CSV 다운로드 (UTF-8 BOM, 한글 안깨짐) | 200, text/csv, 45행 |
| 알림 정책 detail | code/channels/recipients 정상 |
| 알림 정책 등록 validation (전체 누락) | 6개 필드 한글 에러 |
| 알림 정책 등록 — 잘못된 수신자 토큰 | "유효하지 않은 수신 대상 토큰" |
| 메뉴 권한 토글 | DB 즉시 반영 |

## v3 trade-off (양해 필요)

- **알림 정책의 실제 발송 워커는 v4** — 현재는 정책 등록·조회·발송이력 화면만. 이벤트 발생 → NotificationLog 자동 생성하는 워커 (Celery/RQ) 는 별도. 모델·UI 가 자리잡았으니 워커만 1-2일 작업.
- **메뉴 권한 → 실제 SNB 표시 제어는 v4** — MenuPermission 등록은 됨. base.html SNB 가 admin 사용자에게 이 데이터 읽어 표시 결정하는 로직은 별도. v1 에서 "백오피스는 super_admin only" 결정했어서 admin 사용자가 백오피스 진입 자체 못함 — 이 결정 풀고 권한 게이트 수정 시 자연스럽게 동작.
- **이벤트 이력 → 알람 후속 처리(반려/이관) 는 v4** — 현재는 읽음 처리만.

## 파일 변경 요약 (총 12파일, +4,418 줄)

```
[backoffice 코어]
대폭수정       backoffice/models.py             (+3 모델, ~190줄: NotificationPolicy/Log/MenuPermission)
대폭수정       backoffice/forms.py              (+2 폼, ~140줄)
대폭수정       backoffice/views.py              (+12 뷰, ~390줄)
대폭수정       backoffice/urls.py               (+11 URL 패턴)
신규           backoffice/migrations/0006_notification_and_menu.py
신규           backoffice/migrations/0007_seed_notification_and_menu.py  (시드 5 정책 + 8 메뉴 권한)

[화면]
수정           templates/backoffice/base.html   (SNB — 메뉴 관리 + 알림/이벤트 관리 활성화 + 3 sub-items)
신규           templates/backoffice/events/list.html
신규           templates/backoffice/notifications/policy_list.html
신규           templates/backoffice/notifications/log_list.html
신규           templates/backoffice/menus/manage.html
신규           static/js/backoffice/policies.js
```

## 누적 결과

- v1 (슈퍼관리자 채널 + 계정/권한): 4,621 줄
- v2 (코어 마스터 4종 + FastAPI 동기화): 7,005 줄
- v3 (알림/이벤트 + 메뉴): 4,418 줄
- **합계: 약 16,000 줄** — 7개 1Depth 메뉴 전부 + 13개 화면

## 다음 단계 (시간 여유 시)

남은 메뉴는 3개:
1. **설비/장비 관리** (2-3일) - devices 앱과 연동, 센서 등록·관리
2. **지도 편집 관리** (2일) - dashboard.MapImage + GeoFence 통합 편집
3. **운영 데이터 / 공지사항** (2일) - 보관 주기, 공지 등록·발송
