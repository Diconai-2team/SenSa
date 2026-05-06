"""
backoffice/models.py — 백오피스 마스터 모델

- Organization : 회사 / 부서 트리 (피그마 '조직 관리')
- Position     : 직위 (피그마 '직위 관리')

설계 원칙:
  - 조직은 self-FK 트리 구조. 회사가 root, 부서가 leaf.
  - "조직 없음" 가상 부서는 is_unassigned_bucket=True 로 1건 시드 (부서 미지정 사용자가 자동 들어감).
  - 직위는 단순 마스터 (정렬 순서 + 사용 여부).
  - 두 모델 모두 백오피스 액션 추적용 (created_by, updated_by) 필드 포함.

[관계]
  accounts.User.organization  → Organization (FK, nullable)
  accounts.User.position_obj  → Position (FK, nullable)
"""
from django.conf import settings
from django.db import models


# ═══════════════════════════════════════════════════════════
# 조직 (회사 + 부서)
# ═══════════════════════════════════════════════════════════

class Organization(models.Model):
    """
    조직 노드 — 회사 또는 부서.

    parent=None 인 노드가 회사(root). 그 외는 부서.
    소규모 시스템 가정으로 깊이 제한은 두지 않으나,
    UI(조직 트리)는 2-depth (회사 > 부서) 까지만 지원.

    name 은 unique 가 아님 — 같은 회사 안의 부서끼리만 unique 권장(unique_together).
    """
    name = models.CharField(
        max_length=100,
        verbose_name='조직명',
        help_text='회사명 또는 부서명',
    )
    code = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='부서 코드',
        help_text='001, 002 ... 같은 식별 코드 (피그마 디자인)',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='children',
        verbose_name='상위 조직',
        help_text='None 이면 회사(root)',
    )
    description = models.TextField(
        blank=True,
        default='',
        verbose_name='설명',
    )
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='leading_organizations',
        verbose_name='조직장',
        help_text='해당 부서의 조직장 (구성원 중 1명)',
    )
    is_unassigned_bucket = models.BooleanField(
        default=False,
        verbose_name='조직 없음 버킷 여부',
        help_text='True 인 단일 노드가 부서 미지정 사용자의 자동 소속처',
    )
    sort_order = models.IntegerField(
        default=100,
        verbose_name='정렬 순서',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_organizations',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='updated_organizations',
    )

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = '조직'
        verbose_name_plural = '조직 목록'
        # 같은 부모 아래 같은 이름 금지 (회사 트리 안에서 부서명 중복 방지)
        constraints = [
            models.UniqueConstraint(
                fields=['parent', 'name'],
                name='org_unique_name_per_parent',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def member_count(self) -> int:
        """현재 소속 사용자 수"""
        return self.users.count()


# ═══════════════════════════════════════════════════════════
# 직위
# ═══════════════════════════════════════════════════════════

class Position(models.Model):
    """
    직위 마스터.

    피그마 디자인: 대표이사 / 이사 / 부장 / 차장 / 과장 / 대리 / 사원 등
    sort_order 1=최상위 (대표이사), 큰 숫자일수록 하위 직위.
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='직위명',
    )
    sort_order = models.IntegerField(
        default=100,
        verbose_name='정렬 순서',
        help_text='작을수록 상위 직위 (대표이사=1)',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='사용 여부',
        help_text='False 면 신규 사용자 등록 시 선택 목록에서 제외',
    )
    description = models.TextField(
        blank=True,
        default='',
        verbose_name='설명',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_positions',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='updated_positions',
    )

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = '직위'
        verbose_name_plural = '직위 목록'

    def __str__(self):
        return self.name


# ═══════════════════════════════════════════════════════════
# 공통 코드 (CodeGroup + Code) — 피그마 '공통 코드 관리'
# ═══════════════════════════════════════════════════════════
#
# 2-level 마스터:
#   - CodeGroup: DEVICE_TYPE / GAS_TYPE / UNIT_CODE / EVENT_TYPE / NOTIF_CHANNEL ...
#   - Code     : 그룹 안의 개별 코드 (예: GAS_TYPE 그룹 안의 CO/H2S/CH4 ...)
#
# 다른 도메인(임계치/위험유형/장비)이 단위·종류 등을 참조할 때 활용.

class CodeGroup(models.Model):
    code = models.CharField(
        max_length=50, unique=True,
        verbose_name='코드 그룹', help_text='UPPER_SNAKE_CASE (예: DEVICE_TYPE)',
    )
    name = models.CharField(max_length=50, verbose_name='그룹명')
    description = models.TextField(blank=True, default='', verbose_name='설명')
    sort_order = models.IntegerField(default=100, verbose_name='정렬 순서')
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    is_system = models.BooleanField(
        default=False, verbose_name='시스템 그룹 여부',
        help_text='True 면 그룹 자체 삭제 불가 (시드된 핵심 그룹 보호)',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_codegroups')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_codegroups')

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = '코드 그룹'
        verbose_name_plural = '코드 그룹 목록'

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def code_count(self):
        return self.codes.count()


class Code(models.Model):
    group = models.ForeignKey(CodeGroup, on_delete=models.CASCADE, related_name='codes', verbose_name='코드 그룹')
    code = models.CharField(max_length=50, verbose_name='코드')
    name = models.CharField(max_length=100, verbose_name='코드명')
    description = models.TextField(blank=True, default='', verbose_name='설명')
    sort_order = models.IntegerField(default=100, verbose_name='정렬 순서')
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_codes')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_codes')

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = '코드'
        verbose_name_plural = '코드 목록'
        constraints = [
            models.UniqueConstraint(fields=['group', 'code'], name='code_unique_per_group'),
        ]

    def __str__(self):
        return f'{self.group.code}.{self.code}'


# ═══════════════════════════════════════════════════════════
# 위험 유형 (RiskCategory + RiskType) — 피그마 '위험 유형 관리'
# ═══════════════════════════════════════════════════════════
#
# 2-level 마스터:
#   - RiskCategory: RISK_GAS / RISK_POWER / RISK_LOCATION / RISK_WORK ...
#   - RiskType    : 카테고리 안의 개별 유형 (예: GAS_LEAK, POWER_OVERLOAD)
#
# 반영 위치 (applies_to): 실시간 관제 / 이벤트 이력 / 알림 - multi-check.

# applies_to 는 사용 패턴이 많아 별도 테이블 대신 CSV 문자열로 저장 (단순화).
# 화면에서는 'realtime,event,alarm' → ['실시간 관제','이벤트 이력','알림'] 변환.
APPLIES_TO_CHOICES_RISK = [
    ('realtime', '실시간 관제'),
    ('event',    '이벤트 이력'),
    ('alarm',    '알림'),
]

class RiskCategory(models.Model):
    code = models.CharField(max_length=50, unique=True, verbose_name='분류 코드')
    name = models.CharField(max_length=50, verbose_name='분류명')
    description = models.TextField(blank=True, default='', verbose_name='설명')
    applies_to = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='반영 범위',
        help_text='CSV: realtime,event,alarm',
    )
    sort_order = models.IntegerField(default=100, verbose_name='정렬 순서')
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    is_system = models.BooleanField(default=False, verbose_name='시스템 분류 여부')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_risk_categories')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_risk_categories')

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = '위험 분류'
        verbose_name_plural = '위험 분류 목록'

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def applies_to_list(self):
        return [s for s in (self.applies_to or '').split(',') if s]

    @property
    def type_count(self):
        return self.types.count()


class RiskType(models.Model):
    category = models.ForeignKey(RiskCategory, on_delete=models.CASCADE, related_name='types', verbose_name='위험 분류')
    code = models.CharField(max_length=50, verbose_name='유형 코드')
    name = models.CharField(max_length=100, verbose_name='유형명')
    description = models.TextField(blank=True, default='', verbose_name='설명')
    show_on_map = models.BooleanField(default=True, verbose_name='지도 반영 여부')
    sort_order = models.IntegerField(default=100, verbose_name='정렬 순서')
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_risk_types')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_risk_types')

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = '위험 유형'
        verbose_name_plural = '위험 유형 목록'
        constraints = [
            models.UniqueConstraint(fields=['category', 'code'], name='risk_type_unique_per_category'),
        ]

    def __str__(self):
        return f'{self.category.code}.{self.code}'


# ═══════════════════════════════════════════════════════════
# 위험 기준 (AlarmLevel) — 피그마 '위험 기준 관리'
# ═══════════════════════════════════════════════════════════
#
# 단일 레벨 마스터. 알림 단계 (정상/주의/경고/위험 ...) 정의.
# alerts.Alarm 의 level CharField 와 향후 연동.

ALARM_COLOR_CHOICES = [
    ('gray',   '회색'),
    ('green',  '녹색'),
    ('yellow', '황색'),
    ('orange', '주황색'),
    ('red',    '적색'),
    ('black',  '검정색'),
]

ALARM_INTENSITY_CHOICES = [
    ('normal',  '정상'),
    ('caution', '주의'),
    ('warning', '경고'),
    ('danger',  '위험'),
]

class AlarmLevel(models.Model):
    code = models.CharField(
        max_length=50, unique=True,
        verbose_name='단계 코드',
        help_text='UPPER 영문/숫자/언더스코어 (예: WARNING)',
    )
    name = models.CharField(max_length=20, verbose_name='단계명')
    color = models.CharField(max_length=20, choices=ALARM_COLOR_CHOICES, verbose_name='표시 색상')
    intensity = models.CharField(max_length=20, choices=ALARM_INTENSITY_CHOICES, verbose_name='알림 강도')
    priority = models.IntegerField(
        default=100, verbose_name='이벤트 우선순위',
        help_text='작을수록 높은 우선순위 (정상=10, 위험=90 같은 식)',
    )
    description = models.TextField(blank=True, default='', verbose_name='설명')
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    is_system = models.BooleanField(default=False, verbose_name='시스템 단계 여부')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_alarm_levels')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_alarm_levels')

    class Meta:
        ordering = ['priority', 'code']
        verbose_name = '위험 기준'
        verbose_name_plural = '위험 기준 목록'

    def __str__(self):
        return f'{self.name} ({self.code})'


# ═══════════════════════════════════════════════════════════
# 임계치 기준 (ThresholdCategory + Threshold) — 피그마 '임계치 기준 관리'
# ═══════════════════════════════════════════════════════════
#
# **이 모델이 실제로 시스템 동작을 바꾼다.**
# FastAPI generators.py 의 GAS_THRESHOLDS 하드코딩을 대체.
#
# 2-level:
#   - ThresholdCategory: TH_GAS / TH_POWER / TH_AI / TH_COMMON
#   - Threshold       : 카테고리 안의 측정 항목별 임계치
#
# 판단 조건 (operator):
#   - 'over'  → caution_value 초과 시 주의, danger_value 초과 시 위험
#   - 'under' → caution_value 미만 시 주의, danger_value 미만 시 위험 (산소 등)
#
# 반영 범위 (applies_to): realtime / ai_predict / alarm — CSV.

THRESHOLD_OPERATOR_CHOICES = [
    ('over',  '초과'),
    ('under', '이하'),
]

APPLIES_TO_CHOICES_THRESHOLD = [
    ('realtime',   '실시간 관제'),
    ('ai_predict', 'AI 예측'),
    ('alarm',      '알림'),
]

class ThresholdCategory(models.Model):
    code = models.CharField(max_length=50, unique=True, verbose_name='분류 코드')
    name = models.CharField(max_length=50, verbose_name='분류명')
    description = models.TextField(blank=True, default='', verbose_name='설명')
    applies_to = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='반영 범위',
        help_text='CSV: realtime,ai_predict,alarm',
    )
    sort_order = models.IntegerField(default=100, verbose_name='정렬 순서')
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    is_system = models.BooleanField(default=False, verbose_name='시스템 분류 여부')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_threshold_categories')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_threshold_categories')

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = '임계치 분류'
        verbose_name_plural = '임계치 분류 목록'

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def applies_to_list(self):
        return [s for s in (self.applies_to or '').split(',') if s]

    @property
    def threshold_count(self):
        return self.thresholds.count()


class Threshold(models.Model):
    category = models.ForeignKey(ThresholdCategory, on_delete=models.CASCADE, related_name='thresholds', verbose_name='임계치 분류')
    item_code = models.CharField(
        max_length=50, verbose_name='측정 항목 코드',
        help_text='가스: co/h2s/co2/o2/no2/so2/o3/nh3/voc/ch4 — generators.py 키와 일치',
    )
    item_name = models.CharField(max_length=50, verbose_name='측정 항목명')
    unit = models.CharField(max_length=20, verbose_name='단위', help_text='ppm / %LEL / % / A / V')
    operator = models.CharField(
        max_length=10, choices=THRESHOLD_OPERATOR_CHOICES, default='over',
        verbose_name='판단 조건',
    )
    caution_value = models.FloatField(verbose_name='주의값')
    danger_value = models.FloatField(verbose_name='위험값')
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    applies_to = models.CharField(
        max_length=100, blank=True, default='realtime,alarm',
        verbose_name='반영 범위',
        help_text='CSV: realtime,ai_predict,alarm',
    )
    description = models.TextField(blank=True, default='', verbose_name='설명')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_thresholds')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_thresholds')

    class Meta:
        ordering = ['category__sort_order', 'item_code']
        verbose_name = '임계치 기준'
        verbose_name_plural = '임계치 기준 목록'
        constraints = [
            models.UniqueConstraint(fields=['category', 'item_code'], name='threshold_unique_per_category'),
        ]

    def __str__(self):
        return f'{self.category.code}.{self.item_code} ({self.caution_value}/{self.danger_value})'

    @property
    def applies_to_list(self):
        return [s for s in (self.applies_to or '').split(',') if s]


# ═══════════════════════════════════════════════════════════
# 알림 정책 (NotificationPolicy) — 피그마 '알림 정책 관리'
# ═══════════════════════════════════════════════════════════
#
# 정책 1건이 의미하는 것:
#   "어떤 위험 분류 + 어떤 알람 단계의 이벤트가 발생했을 때
#    어떤 채널로 누구에게 알림을 보낼 것인가"
#
# 발송 채널 (channels): 'app,realtime,sms,email' CSV
# 수신 대상 (recipients): 'all_users,leaders,group:<org_id>,role:<role_code>' CSV

NOTIFICATION_CHANNEL_CHOICES = [
    ('app',      '앱 푸시'),
    ('realtime', '관제 실시간'),
    ('sms',      'SMS'),
    ('email',    '이메일'),
]


class NotificationPolicy(models.Model):
    """알림 정책.

    트리거: risk_category 가 발생 + alarm_level 이상.
    대상:   recipients_csv (특수 토큰 + 조직/역할 조합)
    채널:   channels_csv
    """
    code = models.CharField(max_length=50, unique=True, verbose_name='정책 코드')
    name = models.CharField(max_length=100, verbose_name='정책명')
    description = models.TextField(blank=True, default='', verbose_name='설명')

    # 트리거 조건
    risk_category = models.ForeignKey(
        RiskCategory, on_delete=models.CASCADE,
        related_name='policies', verbose_name='적용 위험 분류',
    )
    alarm_level = models.ForeignKey(
        AlarmLevel, on_delete=models.CASCADE,
        related_name='policies', verbose_name='적용 알람 단계',
        help_text='이 단계 이상의 이벤트에 정책 적용 (priority 기준)',
    )

    # 발송 채널 / 수신 대상
    channels_csv = models.CharField(
        max_length=100, default='app,realtime',
        verbose_name='발송 채널',
        help_text='CSV: app,realtime,sms,email',
    )
    recipients_csv = models.CharField(
        max_length=500, default='all_users',
        verbose_name='수신 대상',
        help_text='CSV: all_users / leaders / group:<org_id> / role:<role>',
    )

    # 메시지 템플릿 (선택)
    message_template = models.TextField(
        blank=True, default='',
        verbose_name='메시지 템플릿',
        help_text='{worker_name} {device_id} {value} 등 placeholder 사용 가능',
    )

    # 정책 메타
    is_active = models.BooleanField(default=True, verbose_name='사용 여부')
    sort_order = models.IntegerField(default=100, verbose_name='정렬 순서')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_policies')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_policies')

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = '알림 정책'
        verbose_name_plural = '알림 정책 목록'

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def channels_list(self):
        return [s for s in (self.channels_csv or '').split(',') if s]

    @property
    def recipients_list(self):
        return [s for s in (self.recipients_csv or '').split(',') if s]


class NotificationLog(models.Model):
    """알림 발송 이력 — 1건 = 1 사용자 × 1 채널 × 1 알람 이벤트.

    피그마 명세: 발송 일시 / 정책 / 알람 / 수신자 / 채널 / 결과.
    실제 발송은 v3 에서 알림 워커가 수행. 지금은 모델만 정의 + 화면.
    """
    SEND_STATUS_CHOICES = [
        ('pending',   '대기'),
        ('sent',      '성공'),
        ('failed',    '실패'),
        ('skipped',   '건너뜀'),
    ]
    policy = models.ForeignKey(
        NotificationPolicy, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='logs',
    )
    alarm = models.ForeignKey(
        'alerts.Alarm', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='notification_logs',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='received_notifications',
    )
    recipient_name_snapshot = models.CharField(
        max_length=100, blank=True, default='',
        help_text='수신 시점 사용자명 스냅샷 (탈퇴 후에도 보존)',
    )
    channel = models.CharField(max_length=20, choices=NOTIFICATION_CHANNEL_CHOICES)
    send_status = models.CharField(max_length=20, choices=SEND_STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '알림 발송 이력'
        verbose_name_plural = '알림 발송 이력 목록'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['send_status', '-created_at']),
        ]

    def __str__(self):
        return f'[{self.send_status}] {self.recipient_name_snapshot} via {self.channel}'


# ═══════════════════════════════════════════════════════════
# 메뉴 권한 (MenuPermission) — 피그마 '메뉴 관리'
# ═══════════════════════════════════════════════════════════
#
# 8개 1Depth 메뉴에 대한 역할별 접근 권한.
# v1: super_admin 은 무조건 전체. admin 은 여기 등록된 메뉴만.
#     operator 는 백오피스 진입 자체 불가.

MENU_CODE_CHOICES = [
    ('users',         '계정/권한 관리'),
    ('menus',         '메뉴 관리'),
    ('devices',       '설비/장비 관리'),
    ('maps',          '지도 편집 관리'),
    ('references',    '기준정보 관리'),
    ('operations',    '운영 데이터 관리'),
    ('notices',       '공지사항 관리'),
    ('notifications', '알림/이벤트 관리'),
]


class MenuPermission(models.Model):
    """역할 ↔ 메뉴 매핑.

    하나의 (role, menu_code) 조합당 1건. is_visible/is_writable 토글로 제어.
    super_admin 은 이 테이블 무관 — 항상 전체 접근.
    """
    role = models.CharField(
        max_length=20,
        verbose_name='역할',
        help_text='accounts.User.ROLE_CHOICES 의 코드 — admin/operator',
    )
    menu_code = models.CharField(
        max_length=30, choices=MENU_CODE_CHOICES,
        verbose_name='메뉴',
    )
    is_visible = models.BooleanField(
        default=True, verbose_name='조회 가능',
        help_text='False 면 SNB 에 표시 자체가 안 됨',
    )
    is_writable = models.BooleanField(
        default=False, verbose_name='등록/수정 가능',
        help_text='False 면 페이지 진입은 가능하나 등록/수정 버튼 비활성',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_menu_perms')

    class Meta:
        ordering = ['role', 'menu_code']
        verbose_name = '메뉴 권한'
        verbose_name_plural = '메뉴 권한 목록'
        constraints = [
            models.UniqueConstraint(fields=['role', 'menu_code'], name='menu_perm_unique_role_menu'),
        ]

    def __str__(self):
        return f'{self.role}/{self.menu_code} (visible={self.is_visible}, writable={self.is_writable})'


# ═══════════════════════════════════════════════════════════
# 운영 데이터 보관 정책 (DataRetention) — 피그마 '운영 데이터 관리'
# ═══════════════════════════════════════════════════════════
#
# 시스템 누적 데이터 (센서 히스토리, 알람, 발송 이력 등) 의 보관 기간 정책.
# 실제 삭제는 v4 의 batch (Celery beat) 가 수행 — 지금은 정책 등록·조회 + 통계만.

DATA_TARGET_CHOICES = [
    ('sensor_data',    '센서 측정값 (devices.SensorData)'),
    ('worker_location','작업자 위치 (workers.WorkerLocation)'),
    ('alarms',         '알람 (alerts.Alarm)'),
    ('notification_logs', '알림 발송 이력 (backoffice.NotificationLog)'),
    ('audit_logs',     '감사 로그 (예정)'),
]

class DataRetentionPolicy(models.Model):
    """데이터 보관 주기 정책. 단일 target 당 1건 권장."""
    target = models.CharField(
        max_length=30, choices=DATA_TARGET_CHOICES, unique=True,
        verbose_name='대상 데이터',
    )
    retention_days = models.IntegerField(
        default=90, verbose_name='보관 기간 (일)',
        help_text='이 기간 이전 데이터는 삭제 대상',
    )
    is_active = models.BooleanField(default=True, verbose_name='정책 활성화')
    last_run_at = models.DateTimeField(null=True, blank=True, verbose_name='최근 정리 일시')
    last_run_deleted = models.IntegerField(default=0, verbose_name='최근 삭제 건수')
    description = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='updated_retention_policies',
    )

    class Meta:
        ordering = ['target']
        verbose_name = '운영 데이터 보관 정책'
        verbose_name_plural = '운영 데이터 보관 정책'

    def __str__(self):
        return f'{self.get_target_display()} — {self.retention_days}일'


# ═══════════════════════════════════════════════════════════
# 공지사항 (Notice) — 피그마 '공지사항 관리'
# ═══════════════════════════════════════════════════════════

NOTICE_CATEGORY_CHOICES = [
    ('system',     '시스템 공지'),
    ('safety',     '안전 안내'),
    ('event',      '이벤트/행사'),
    ('maintenance','정기 점검'),
    ('other',      '기타'),
]


class Notice(models.Model):
    """공지사항. 게시 기간 + 중요 표시 + 작성자 추적."""
    title = models.CharField(max_length=200, verbose_name='제목')
    category = models.CharField(
        max_length=20, choices=NOTICE_CATEGORY_CHOICES, default='system',
        verbose_name='카테고리',
    )
    content = models.TextField(verbose_name='내용')
    is_pinned = models.BooleanField(default=False, verbose_name='상단 고정')
    is_published = models.BooleanField(default=True, verbose_name='게시 중')
    published_from = models.DateTimeField(null=True, blank=True, verbose_name='게시 시작일시')
    published_to = models.DateTimeField(null=True, blank=True, verbose_name='게시 종료일시')
    view_count = models.IntegerField(default=0, verbose_name='조회수')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_notices',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='updated_notices',
    )

    class Meta:
        ordering = ['-is_pinned', '-created_at']
        verbose_name = '공지사항'
        verbose_name_plural = '공지사항 목록'
        indexes = [
            models.Index(fields=['-is_pinned', '-created_at']),
            models.Index(fields=['category', '-created_at']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_currently_published(self):
        """현재 시점 기준 실제로 게시 중인지."""
        from django.utils import timezone
        now = timezone.now()
        if not self.is_published:
            return False
        if self.published_from and now < self.published_from:
            return False
        if self.published_to and now > self.published_to:
            return False
        return True


# ═══════════════════════════════════════════════════════════
# 감사 로그 (AuditLog) — v6 신규
# ═══════════════════════════════════════════════════════════
#
# 백오피스에서 발생하는 모든 변경 액션 (등록/수정/삭제) 을 기록.
# 누가, 언제, 어떤 객체를, 어떻게 바꿨는지 추적.
#
# 자동 기록 트리거:
#   - 시그널 (post_save, post_delete) — 단순 case
#   - 미들웨어 (request 단위) — 일괄 액션, IP 추적
#
# 규모 가정: 백오피스 액션 빈도 낮음 (분당 < 10건). DB 쓰기 부담 없음.
# 운영 1년치 = 약 5만 건. retention 365일 정책으로 관리 (DataRetentionPolicy 'audit_logs').

AUDIT_ACTION_CHOICES = [
    ('create', '등록'),
    ('update', '수정'),
    ('delete', '삭제'),
    ('login',  '로그인'),
    ('logout', '로그아웃'),
    ('login_fail', '로그인 실패'),
    ('bulk_op',    '일괄 처리'),
    ('csv_upload', 'CSV 업로드'),
    ('cleanup',    '데이터 정리'),
    ('dispatch',   '알림 발송'),
]


class AuditLog(models.Model):
    """백오피스 액션 추적.

    설계:
      - actor: 액션 수행자 (user). 비로그인 시 None.
      - target_*: 변경 대상 객체 (앱.모델 + PK + 표시명).
        문자열로 저장 — FK 두면 대상 삭제 시 cascade로 사라지므로.
      - changes: 변경 내역 JSON. {"field": [old, new]} 또는 단순 메모.
      - ip_address: 미들웨어가 채움.
    """
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        verbose_name='수행자',
    )
    actor_username_snapshot = models.CharField(
        max_length=150, blank=True, default='',
        help_text='수행자 username 스냅샷 (사용자 삭제 후에도 보존)',
    )
    action = models.CharField(max_length=20, choices=AUDIT_ACTION_CHOICES, verbose_name='액션')
    target_app = models.CharField(max_length=50, blank=True, default='', verbose_name='대상 앱')
    target_model = models.CharField(max_length=50, blank=True, default='', verbose_name='대상 모델')
    target_pk = models.CharField(max_length=50, blank=True, default='', verbose_name='대상 PK')
    target_repr = models.CharField(
        max_length=200, blank=True, default='',
        verbose_name='대상 표시명',
        help_text='str(obj) 스냅샷 (대상 삭제 후에도 무엇을 지웠는지 추적)',
    )
    changes = models.JSONField(default=dict, blank=True, verbose_name='변경 내역')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP 주소')
    request_path = models.CharField(max_length=500, blank=True, default='', verbose_name='요청 경로')
    extra_message = models.CharField(max_length=300, blank=True, default='', verbose_name='추가 메모')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '감사 로그'
        verbose_name_plural = '감사 로그 목록'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['actor', '-created_at']),
            models.Index(fields=['target_model', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return f'[{self.action}] {self.actor_username_snapshot or "anon"} → {self.target_model}#{self.target_pk}'


# ═══════════════════════════════════════════════════════════
# 장비 변경 이력 (DeviceHistory) — v6 신규
# ═══════════════════════════════════════════════════════════
#
# 장비 단위로 좁힌 이력. AuditLog 와 별도 테이블 — 장비 화면에서
# "이 장비 누가 언제 어떻게 바꿨나" 를 빠르게 보기 위함.
# AuditLog 가 시스템 전체 audit 라면, DeviceHistory 는 장비 카드 안의 history tab 용.

class DeviceHistory(models.Model):
    DEVICE_HISTORY_ACTION_CHOICES = [
        ('create',     '등록'),
        ('update',     '수정'),
        ('delete',     '삭제'),
        ('move',       '좌표 이동'),
        ('toggle',     '활성/비활성'),
        ('csv_import', 'CSV 일괄 등록'),
    ]
    device_id_snapshot = models.CharField(max_length=50, db_index=True, verbose_name='장비 ID 스냅샷')
    device = models.ForeignKey(
        'devices.Device', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='history_logs',
        verbose_name='장비',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    actor_username_snapshot = models.CharField(max_length=150, blank=True, default='')
    action = models.CharField(max_length=20, choices=DEVICE_HISTORY_ACTION_CHOICES)
    changes = models.JSONField(default=dict, blank=True)
    extra_message = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '장비 변경 이력'
        verbose_name_plural = '장비 변경 이력'
        indexes = [
            models.Index(fields=['device_id_snapshot', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f'[{self.action}] {self.device_id_snapshot} by {self.actor_username_snapshot or "anon"}'
