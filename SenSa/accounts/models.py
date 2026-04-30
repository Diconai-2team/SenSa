from django.contrib.auth.models import AbstractUser
# Django 기본 User 모델의 추상 베이스 클래스를 불러와 — 인증 기능을 그대로 물려받기 위해서야
from django.db import models
# 모델 필드 타입(CharField, ForeignKey 등)을 정의하기 위한 ORM 모듈이야


class User(AbstractUser):
    """
    커스텀 유저 모델.

    AbstractUser를 상속하여 Django의 모든 인증 기능을 그대로 사용한다.
    username, password, email, first_name, last_name, is_active,
    is_staff, is_superuser, date_joined, last_login 등이 자동 제공된다.

    [변경 이력]
      v1 : role / department / phone 필드
      v2 : position (직급) 필드 추가 — 내 정보 페이지 표시용
      v3 (백오피스 — 슈퍼관리자 채널):
           - role 에 'super_admin' 추가 (기존 admin/operator 보존)
           - is_locked 필드 추가 (사용/잠금/비활성 3-state 의 '잠금' 분리)
           - organization / position_obj FK 신설 (점진 마이그레이션,
             기존 free-text department/position 도 유지하여 무중단)
    """

    ROLE_CHOICES = [
    # role 필드의 선택 가능한 값과 화면 표시 이름의 매핑 리스트야
        ('operator', '운영자'),
        # DB에는 'operator'로 저장되고 화면엔 '운영자'로 표시 — 일반 사용자/현장 운영자 등급
        ('admin', '관리자'),
        # 'admin'은 기존 일반 관리자 — 백오피스 일부 메뉴 권한을 가져
        ('super_admin', '슈퍼관리자'),
        # 'super_admin'은 v3 신규 — 백오피스 전체 권한을 가지는 최상위 비즈니스 역할이야
    ]

    role = models.CharField(
    # 사용자 역할을 저장하는 문자열 필드 — 위 ROLE_CHOICES에서 선택된 값만 들어올 수 있어
        max_length=20,
        # 최대 20자 — 'super_admin'이 11자라 충분히 여유 있어
        choices=ROLE_CHOICES,
        # 위에서 정의한 선택지로만 값을 제한해
        default='operator',
        # 기본값은 '운영자' — 회원가입 시 별도 지정 없으면 자동으로 이 값이 들어가
        verbose_name='역할',
        # admin 페이지/폼에서 사람이 읽는 라벨 이름이야
    )
    department = models.CharField(
    # 소속 부서명을 자유 텍스트로 저장하는 필드 — legacy 호환용으로 남겨둔 거야
        max_length=100,
        # 부서명 최대 100자
        blank=True,
        # 폼 검증 시 빈 값 허용 (필수 입력 아님)
        default='',
        # DB 기본값은 빈 문자열 — null 대신 빈 문자열로 통일하는 Django 컨벤션이야
        verbose_name='소속 부서',
        help_text='legacy free-text. 새 백오피스는 organization FK 사용 권장',
        # admin 폼에 표시되는 안내 — 신규 코드는 organization FK를 쓰라는 마이그레이션 가이드야
    )
    position = models.CharField(
    # 직급명을 자유 텍스트로 저장 — 마찬가지로 legacy 호환용 필드야
        max_length=50,
        blank=True,
        default="",
        verbose_name="직급",
        help_text="legacy free-text. 새 백오피스는 position_obj FK 사용 권장",
    )
    phone = models.CharField(
    # 사용자 연락처를 문자열로 저장 — 형식 검증은 별도 없이 자유 입력이야
        max_length=20,
        blank=True,
        default="",
        verbose_name="연락처",
    )

    # ─── v3 신규 — 계정 잠금 (피그마 '계정 상태' 의 '잠금' 상태) ───
    # is_active=True, is_locked=False → 사용
    # is_active=True, is_locked=True  → 잠금
    # is_active=False                  → 비활성
    is_locked = models.BooleanField(
    # 계정이 '잠금' 상태인지 여부를 저장하는 불리언 필드 — is_active와는 독립적이야
        default=False,
        # 기본값 False — 잠기지 않은 상태로 시작해
        verbose_name='계정 잠금 여부',
        help_text='관리자 잠금 / 비밀번호 N회 실패 잠금. is_active 와 독립.',
        # is_active(비활성)와 분리해서 '사용/잠금/비활성' 3-state를 표현하기 위한 필드야
    )

    # ─── v3 신규 — 조직/직위 FK (선택) ───
    organization = models.ForeignKey(
    # 정규화된 조직 테이블(backoffice.Organization)과의 FK — legacy department를 점진 대체해
        'backoffice.Organization',
        # 문자열로 참조 — backoffice 앱이 아직 로드되지 않아도 순환 import 회피 가능
        on_delete=models.SET_NULL,
        # 조직이 삭제돼도 사용자는 남기고 이 FK만 NULL로 만들어 — 데이터 보존이 우선이야
        null=True, blank=True,
        # DB와 폼 모두에서 NULL/빈 값 허용 — 점진 마이그레이션을 위해 필수
        related_name='users',
        # 역참조 이름 — Organization 인스턴스에서 .users.all()로 소속 사용자를 조회 가능해져
        verbose_name='소속 조직',
    )
    position_obj = models.ForeignKey(
    # 정규화된 직위 테이블(backoffice.Position)과의 FK — legacy position을 대체할 신규 필드야
        'backoffice.Position',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="직위",
    )

    class Meta:
        # 모델의 메타 옵션을 정의하는 내부 클래스야
        db_table = 'accounts_user'
        # 실제 DB 테이블명을 명시적으로 지정 — Django 기본 명명 규칙과 동일하지만 의도를 드러내려는 의도
        verbose_name = '사용자'
        # admin 페이지에 표시될 단수 이름
        verbose_name_plural = '사용자 목록'
        # admin 페이지에 표시될 복수 이름 (한국어는 단복수가 같지만 자연스러운 표현으로)

    def __str__(self):
        # 객체를 문자열로 변환할 때 호출 — admin/shell/로그에서 보기 좋게 만들어주는 역할이야
        return f"{self.username} ({self.get_role_display()})"
        # 'hojun (운영자)' 같은 형식으로 출력 — get_role_display()는 choices의 라벨을 가져와

    # ═══════════════════════════════════════════════════════
    # 권한 헬퍼
    # ═══════════════════════════════════════════════════════
    @property
    # 메서드를 속성처럼 호출할 수 있게 해주는 데코레이터 — user.is_admin_role 형태로 사용 가능해져
    def is_admin_role(self):
        """legacy 호환 — 'admin' 역할"""
        return self.role == 'admin'
        # role 필드가 정확히 'admin'일 때만 True — 템플릿/뷰에서 권한 체크 단축어로 쓰기 위함이야

    @property
    def is_super_admin_role(self):
        """슈퍼관리자 (백오피스 전체 권한) 여부."""
        return self.role == 'super_admin'
        # Django 내장 is_superuser와 별개의 비즈니스 개념 — 둘이 일치하지 않을 수 있음에 주의


    # ═══════════════════════════════════════════════════════
    # 계정 상태 (피그마: 사용/잠금/비활성 3-state)
    # ═══════════════════════════════════════════════════════
    ACCOUNT_STATUS_ACTIVE = 'active'
    # '사용' 상태를 나타내는 상수 — 매직 스트링을 피하고 IDE 자동완성/리팩토링 안전성 확보용이야
    ACCOUNT_STATUS_LOCKED = 'locked'
    # '잠금' 상태 상수
    ACCOUNT_STATUS_DISABLED = 'disabled'
    # '비활성' 상태 상수

    @property
    def account_status(self) -> str:
        # 현재 계정의 3-state 상태를 계산해 문자열로 돌려주는 프로퍼티야
        if not self.is_active:
            return self.ACCOUNT_STATUS_DISABLED
            # is_active가 False면 다른 조건 무시하고 '비활성' — 가장 강한 차단 상태
        if self.is_locked:
            return self.ACCOUNT_STATUS_LOCKED
            # is_active=True이면서 is_locked=True → '잠금'
        return self.ACCOUNT_STATUS_ACTIVE
        # 둘 다 아니면 정상 '사용' 상태

    @property
    def account_status_display(self) -> str:
        # 위 상태 코드를 한국어 라벨로 매핑해서 돌려주는 화면 표시 전용 프로퍼티야
        return {
            self.ACCOUNT_STATUS_ACTIVE: "사용",
            self.ACCOUNT_STATUS_LOCKED: "잠금",
            self.ACCOUNT_STATUS_DISABLED: "비활성",
        }[self.account_status]
        # dict 즉시 인덱싱 방식 — KeyError 가능성은 위 account_status가 3개 값만 반환하므로 닫혀있음

    @property
    def display_organization(self) -> str:
        """화면 표시용 — FK 우선, 없으면 legacy department"""
        if self.organization_id:
        # FK가 연결돼 있는지 _id 필드로 검사 — DB 추가 조회 없이 빠르게 확인 가능해
            return self.organization.name
            # FK가 있으면 정규화된 조직명을 반환 (이때 한 번 추가 쿼리 발생 — N+1 주의)
        return self.department or '-'
        # FK가 없으면 legacy 텍스트 사용 — 그것도 비어있으면 '-' 표시

    @property
    def display_position(self) -> str:
        # display_organization과 동일한 패턴의 직위 버전이야
        if self.position_obj_id:
            return self.position_obj.name
        return self.position or "-"
