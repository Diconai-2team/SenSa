from django.contrib.auth.models import AbstractUser
from django.db import models


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
        ('operator', '운영자'),       # 기존 (= 피그마 '관리자' 와 가까운 의미)
        ('admin', '관리자'),          # 기존
        ('super_admin', '슈퍼관리자'),  # 신규 — 백오피스 전체 권한
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='operator',
        verbose_name='역할',
    )
    department = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='소속 부서',
        help_text='legacy free-text. 새 백오피스는 organization FK 사용 권장',
    )
    position = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='직급',
        help_text='legacy free-text. 새 백오피스는 position_obj FK 사용 권장',
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='연락처',
    )

    # ─── v3 신규 — 계정 잠금 (피그마 '계정 상태' 의 '잠금' 상태) ───
    # is_active=True, is_locked=False → 사용
    # is_active=True, is_locked=True  → 잠금
    # is_active=False                  → 비활성
    is_locked = models.BooleanField(
        default=False,
        verbose_name='계정 잠금 여부',
        help_text='관리자 잠금 / 비밀번호 N회 실패 잠금. is_active 와 독립.',
    )

    # ─── v3 신규 — 조직/직위 FK (선택) ───
    organization = models.ForeignKey(
        'backoffice.Organization',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='users',
        verbose_name='소속 조직',
    )
    position_obj = models.ForeignKey(
        'backoffice.Position',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='users',
        verbose_name='직위',
    )

    class Meta:
        db_table = 'accounts_user'
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    # ═══════════════════════════════════════════════════════
    # 권한 헬퍼
    # ═══════════════════════════════════════════════════════
    @property
    def is_admin_role(self):
        """legacy 호환 — 'admin' 역할"""
        return self.role == 'admin'

    @property
    def is_super_admin_role(self):
        """슈퍼관리자 (백오피스 전체 권한) 여부.
        Django built-in is_superuser 와 별개의 비즈니스 개념."""
        return self.role == 'super_admin'

    # ═══════════════════════════════════════════════════════
    # 계정 상태 (피그마: 사용/잠금/비활성 3-state)
    # ═══════════════════════════════════════════════════════
    ACCOUNT_STATUS_ACTIVE = 'active'      # 사용
    ACCOUNT_STATUS_LOCKED = 'locked'      # 잠금
    ACCOUNT_STATUS_DISABLED = 'disabled'  # 비활성

    @property
    def account_status(self) -> str:
        if not self.is_active:
            return self.ACCOUNT_STATUS_DISABLED
        if self.is_locked:
            return self.ACCOUNT_STATUS_LOCKED
        return self.ACCOUNT_STATUS_ACTIVE

    @property
    def account_status_display(self) -> str:
        return {
            self.ACCOUNT_STATUS_ACTIVE: '사용',
            self.ACCOUNT_STATUS_LOCKED: '잠금',
            self.ACCOUNT_STATUS_DISABLED: '비활성',
        }[self.account_status]

    @property
    def display_organization(self) -> str:
        """화면 표시용 — FK 우선, 없으면 legacy department"""
        if self.organization_id:
            return self.organization.name
        return self.department or '-'

    @property
    def display_position(self) -> str:
        if self.position_obj_id:
            return self.position_obj.name
        return self.position or '-'
