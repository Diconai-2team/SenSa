# 백오피스 — 슈퍼관리자 채널 (3차 결과물 / 데드라인 5/6)

## 포함 범위

- ✅ Role: `super_admin` 추가 (기존 admin/operator 보존, role 겹침 허용)
- ✅ 로그인 분기: 슈퍼관리자 → `/backoffice/`, 그 외 → `/dashboard/`
- ✅ 권한 게이트: 비-슈퍼관리자 페이지 접근 시 403, API 접근 시 401/403 JSON
- ✅ 셸 (헤더 + SNB 8개 메뉴 + 본문) — 활성: 사용자/조직/직위, 그 외 placeholder ("준비 중" 토스트)
- ✅ 사용자 관리: 검색·필터·정렬 5종·페이지네이션·등록/수정/삭제·잠금/잠금해제
- ✅ 조직 관리: 조직 트리 + 부서 정보 + 구성원 카드 + 추가/이동/제외/조직장 임명
- ✅ 직위 관리: 등록/수정/일괄삭제 + 사용 여부 토글
- ✅ 시드 데이터: (주)가람이앤지 + 부서 13개 + "조직 없음" 가상 부서 1개 + 직위 7종
- ✅ 잠금/비활성 계정 로그인 차단

## 적용 순서

1. 압축 해제 후 기존 SenSa 프로젝트 위에 덮어쓰기.
2. `python manage.py migrate` 실행.
   - `accounts.0003_super_admin_and_lock` + `backoffice.0001 / 0002 / 0003` 적용
   - 시드 데이터(조직/직위)는 0002 에서 idempotent 하게 들어감 (재실행 무해)
3. 슈퍼관리자 계정 생성 (Django shell):

    ```python
    python manage.py shell

    from django.contrib.auth import get_user_model
    from backoffice.models import Organization, Position
    U = get_user_model()
    org = Organization.objects.filter(name='시스템운영팀').first()
    pos = Position.objects.filter(name='부장').first()
    U.objects.create_user(
        username='superadmin', password='admin1234',
        first_name='홍길동', email='super.admin@system.co.kr',
        role='super_admin', organization=org, position_obj=pos,
    )
    ```

4. `python manage.py runserver` → 로그인 → 자동으로 `/backoffice/` 이동 → 좌측 SNB 에서 메뉴 선택.

## 검증된 케이스 (테스트 클라이언트로 확인 완료)

| 케이스 | 결과 |
|---|---|
| 비로그인 페이지 접근 | 302 → 로그인 페이지 |
| 운영자 백오피스 페이지 접근 | 403 |
| 슈퍼관리자 백오피스 접근 | 200 |
| 로그인 후 분기 | super_admin → /backoffice/, operator → /dashboard/ |
| 사용자 등록 (필수 누락) | 400 + 필드별 한글 에러 메시지 (피그마 명세 일치) |
| 사용자 등록 (정상) | 200 + 목록 즉시 반영 |
| 중복 아이디 등록 시도 | 400 "이미 사용 중인 아이디입니다." |
| 비밀번호 불일치 | 400 "비밀번호가 일치하지 않습니다." |
| 조직 detail API | 부서 정보 + 구성원 목록 |
| 직위 등록 API | 200 |
| 비-슈퍼관리자 API 접근 | 403 JSON |

## v1 trade-off (양해 필요)

- **겸직 미지원** — 구성원 추가 시 단일 조직만 가능 (v2 에서 다대다 지원 예정)
- **조직 트리 드래그앤드롭 정렬은 v2** — 현재는 sort_order 직접 입력
- **백오피스 액션 감사 로그는 v2** — 현재는 created_by/updated_by 만 기록
- **legacy `User.department` / `User.position` free-text 필드는 보존** — display 시 FK 우선,
  기존 데이터(Worker.department 등) 무중단 호환

## 파일 변경 요약

```
신규  backoffice/                                                    (Django 앱 전체, 7파일)
신규  backoffice/migrations/                                          (3파일)
신규  templates/backoffice/                                           (5파일: base/403/landing/users/orgs/positions)
신규  static/css/backoffice/main.css                                  (~600줄, 디자인 토큰 + 컴포넌트)
신규  static/js/backoffice/                                           (3파일: users/organizations/positions)
수정  accounts/models.py                                              (super_admin role + is_locked + FK)
수정  accounts/views.py                                               (로그인 분기 + 잠금/비활성 차단)
신규  accounts/migrations/0003_super_admin_and_lock.py
수정  mysite/settings.py                                              ('backoffice' INSTALLED_APPS 추가)
수정  mysite/urls.py                                                  (/backoffice/ include 추가)
```

## 다음 단계 (4차 — 시간 여유 시)

피그마 명세 기준 다음 우선순위:
1. **임계치 기준 관리** (실제 시스템 동작에 영향, FastAPI 동기화 필요)
2. **위험 유형 / 위험 기준 관리**
3. **공통 코드 관리**
4. **메뉴 관리** (역할별 메뉴 노출 권한)
5. **알림 정책 / 발송 이력 / 이벤트 이력**
6. **운영 데이터 관리 / 보관 주기**
7. **공지사항 / 안전 확인 / 로그 및 연동 관리**
