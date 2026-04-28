# 백오피스 v4 — 마지막 3개 메뉴 (설비/장비, 지도 편집, 운영 데이터, 공지사항)

v3 위에 적용. **백오피스 8개 1Depth 메뉴 전부 활성화 완료**.

## 포함 범위

### 신규 화면 5종

| 메뉴 | 모델 | 기능 |
|---|---|---|
| **설비/장비 관리** | devices.Device | 검색·필터(타입/상태/활성)·페이지네이션·등록·수정·일괄 활성화/비활성화/삭제. 좌표 + 지오펜스 FK 매핑 |
| **지도 편집 관리** | dashboard.MapImage + geofence.GeoFence + devices.Device | 캔버스 기반 시각 편집기 — 지도 배경 + 지오펜스 폴리곤 그리기 (클릭 → 첫 점 클릭으로 닫기) + 장비 마커 표시. 우측 패널에서 지오펜스 목록 클릭 → 상세 편집 |
| **운영 데이터 관리** | DataRetentionPolicy (신규) | 5종 데이터(센서/위치/알람/알림이력/감사) 보관 기간 설정. 현재 누적 건수 조회 |
| **공지사항 관리** | Notice (신규) | 검색·필터·페이지네이션·등록·수정·일괄 게시/중지/삭제. 상단 고정·게시 기간(datetime) 지원 |

### 백오피스 메뉴 활성화 — 100% 완료

| 1Depth | 상태 |
|---|---|
| 계정/권한 관리 | ✅ v1 |
| 메뉴 관리 | ✅ v3 |
| **설비/장비 관리** | ✅ **v4** |
| **지도 편집 관리** | ✅ **v4** |
| 기준정보 관리 (4종) | ✅ v2 |
| **운영 데이터 관리** | ✅ **v4** |
| **공지사항 관리** | ✅ **v4** |
| 알림/이벤트 관리 (3종) | ✅ v3 |

## 적용 순서

1. v3 적용된 SenSa 위에 압축 해제
2. `python manage.py migrate` — backoffice.0008 + 0009 적용
3. Django 재시작 → SNB 호버 → 8개 메뉴 모두 활성화 확인

## 검증된 케이스

| 케이스 | 결과 |
|---|---|
| 4개 신규 페이지 응답 | 200 |
| 장비 등록 validation (5개 필드) | 한글 에러 메시지 |
| 장비 등록 (정상) | 200 |
| 지오펜스 폴리곤 검증 — 점 2개 | "최소 3개의 좌표가 필요합니다" |
| 지오펜스 폴리곤 검증 — 정상 | 200 |
| 공지 게시 종료일 < 시작일 | "게시 종료일은 시작일 이후여야 합니다" |
| 보관 정책 수정 | DB 즉시 반영 |

## 지도 편집기 동작

- 좌측 캔버스: 지도 배경 + 지오펜스 폴리곤 (구역 유형별 색상) + 장비 마커 (센서 타입별 색상) + 라벨
- 상단 툴바: 선택 / 폴리곤 그리기 / 취소
- 폴리곤 그리기: 점 차례로 클릭 → 마지막에 첫 점(노란색) 근처 클릭으로 도형 닫기 → 등록 모달 자동 오픈 (좌표 자동 채움)
- 우측 패널: 지오펜스 목록 → 클릭 시 상세 편집 + 삭제 버튼

## v4 trade-off (양해)

- **지도 편집 — 폴리곤 점 드래그 편집**: 기존 polygon 의 개별 점을 드래그로 옮기는 기능은 v5. 현재는 JSON 텍스트 직접 편집 또는 새로 그리기.
- **장비 → 지오펜스 자동 매핑**: 등록 시 좌표가 어떤 폴리곤 안에 있는지 자동 감지는 v5. 현재는 dropdown 으로 수동 선택.
- **운영 데이터 정리 batch**: DataRetentionPolicy 등록·UI 만 완성. 실제 보관기간 지난 데이터 삭제하는 Celery batch 는 v5 (1일).
- **공지사항 → 사용자 알림 발송**: Notice 등록만. 등록 시 자동 발송은 v5.
- **장비 일괄 CSV 업로드**: 단건 등록만. v5 에서 추가 가능.

## 파일 변경 요약 (총 14파일, +5,627 줄)

```
[backoffice 코어]
대폭수정       backoffice/models.py             (+2 모델: DataRetentionPolicy, Notice)
대폭수정       backoffice/forms.py              (+4 폼: Device, GeoFence, Retention, Notice)
대폭수정       backoffice/views.py              (+18 뷰)
대폭수정       backoffice/urls.py               (+15 URL 패턴)
신규           backoffice/migrations/0008_retention_and_notice.py
신규           backoffice/migrations/0009_seed_retention_and_notice.py

[화면]
수정           templates/backoffice/base.html   (SNB — 마지막 3개 메뉴 활성화)
신규           templates/backoffice/devices/list.html
신규           templates/backoffice/maps/edit.html               ← 캔버스 편집기 포함
신규           templates/backoffice/operations/retention_list.html
신규           templates/backoffice/notices/list.html
신규           static/js/backoffice/devices.js
신규           static/js/backoffice/maps.js                       ← 캔버스 + 폴리곤 그리기 로직
신규           static/js/backoffice/notices.js
```

## 누적 결과 (v1 + v2 + v3 + v4)

- **약 21,500줄, 18개 화면, 8개 1Depth 메뉴 100% 완성**
- 모든 화면 테스트 클라이언트로 동작 검증
- 5/6 데모 시점에 **백오피스에서 시스템 운영 마스터 데이터 전부를 컨트롤 가능**

| 운영 영역 | 백오피스에서 가능 |
|---|---|
| 사용자/조직/직위 | ✅ 등록·수정·삭제·잠금·이동·조직장 임명 |
| 권한 관리 | ✅ admin 역할 메뉴별 노출/등록 권한 토글 |
| 임계치 운영 중 변경 | ✅ FastAPI 5초 동기화 (CO 임계치 35로 바꾸면 즉시 반영) |
| 위험 분류·기준 정의 | ✅ 분류·유형·알람단계 |
| 알림 정책 | ✅ 위험분류+레벨 트리거 + 채널·수신자 매핑 |
| 이벤트 이력·추출 | ✅ CSV 다운로드 (UTF-8 BOM, 한글 OK) |
| 발송 이력 모니터링 | ✅ 24h 통계 + 검색·필터 |
| 장비 관리 | ✅ 센서·전력·위치 노드 등록·수정 |
| 지도 편집 | ✅ 캔버스 + 폴리곤 그리기 |
| 데이터 보관 정책 | ✅ 5종 데이터 보관 기간 |
| 공지사항 | ✅ 카테고리·고정·게시 기간 |
