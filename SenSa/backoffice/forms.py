"""
backoffice/forms.py — 사용자/조직/직위 등록·수정 폼

피그마 명세의 validation 메시지를 그대로 반영.
공통 규칙:
  - 미입력  → "X 을(를) 입력해 주세요."
  - 형식 오류 → "X 형식이 올바르지 않습니다." 등
  - 중복     → "이미 사용 중인 X 입니다."
  - 길이 초과 → "X 은 N자 이하로 입력해 주세요."

Trade-off (v1 단순화):
  - 비밀번호 "영문/숫자/특수문자 중 2가지 이상" 규칙은 적용 (피그마 그대로)
  - 사용자명 "한글/영문/숫자만" 규칙 적용
  - 이메일은 Django 기본 EmailValidator + 100자 제한
"""
import re

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import EmailValidator

from .models import (
    # v1 (계정/조직)
    Organization, Position,
    # v2 (기준정보)
    CodeGroup, Code, RiskCategory, RiskType, AlarmLevel,
    ThresholdCategory, Threshold,
    ALARM_COLOR_CHOICES, ALARM_INTENSITY_CHOICES,
    THRESHOLD_OPERATOR_CHOICES,
    # v3 (알림/메뉴)
    NotificationPolicy, MenuPermission,
    NOTIFICATION_CHANNEL_CHOICES, MENU_CODE_CHOICES,
    # v4 (운영/공지)
    DataRetentionPolicy, Notice,
    DATA_TARGET_CHOICES, NOTICE_CATEGORY_CHOICES,
)

# 외부 앱 모델 (forms 에서 직접 사용)
from devices.models import (
    Device,
    SENSOR_TYPE_CHOICES as DEVICE_SENSOR_TYPE_CHOICES,
    STATUS_CHOICES as DEVICE_STATUS_CHOICES,
)
from geofence.models import GeoFence, ZONE_TYPE_CHOICES, RISK_LEVEL_CHOICES


User = get_user_model()


# ═══════════════════════════════════════════════════════════
# 공통 헬퍼
# ═══════════════════════════════════════════════════════════

USERNAME_RE = re.compile(r'^[A-Za-z0-9가-힣]+$')        # 한글/영문/숫자만
LOGIN_ID_RE = re.compile(r'^[A-Za-z0-9]+$')             # 영문/숫자만
PHONE_RE    = re.compile(r'^\d{2,4}-?\d{3,4}-?\d{4}$')


def _strip_or_blank(value: str | None) -> str:
    return (value or '').strip()


# ═══════════════════════════════════════════════════════════
# 사용자 등록 폼 (모든 필수값 + validation)
# ═══════════════════════════════════════════════════════════

class UserCreateForm(forms.Form):
    """피그마 사용자 등록 모달의 validation 명세를 코드로 옮긴 폼."""

    name           = forms.CharField(required=False)   # 사용자명 (first_name 에 저장)
    username       = forms.CharField(required=False)   # 아이디 (login id)
    password       = forms.CharField(required=False)
    password_check = forms.CharField(required=False)
    organization   = forms.IntegerField(required=False)  # Organization PK
    role           = forms.CharField(required=False)
    position_obj   = forms.IntegerField(required=False)  # Position PK
    account_status = forms.CharField(required=False)   # 'active' | 'disabled'
    email          = forms.CharField(required=False)
    phone          = forms.CharField(required=False)

    # ── 사용자명 (=name, first_name 에 저장) ──
    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('사용자명을 입력해 주세요.')
        if len(v) < 2:
            raise forms.ValidationError('사용자명을 2자 이상 입력해 주세요.')
        if len(v) > 20:
            raise forms.ValidationError('사용자명은 20자 이하로 입력해 주세요.')
        if not USERNAME_RE.fullmatch(v):
            raise forms.ValidationError(
                '사용자명은 한글, 영문, 숫자만 입력할 수 있습니다.'
            )
        return v

    # ── 아이디 (login id, username 에 저장) ──
    def clean_username(self):
        v = _strip_or_blank(self.cleaned_data.get('username'))
        if not v:
            raise forms.ValidationError('아이디를 입력해 주세요.')
        if ' ' in v:
            raise forms.ValidationError('아이디에는 공백을 입력할 수 없습니다.')
        if len(v) < 4:
            raise forms.ValidationError('아이디를 4자 이상 입력해 주세요.')
        if len(v) > 20:
            raise forms.ValidationError('아이디는 20자 이하로 입력해 주세요.')
        if not LOGIN_ID_RE.fullmatch(v):
            raise forms.ValidationError(
                '아이디는 영문 또는 숫자만 입력할 수 있습니다.'
            )
        if User.objects.filter(username=v).exists():
            raise forms.ValidationError('이미 사용 중인 아이디입니다.')
        return v

    # ── 비밀번호 ──
    def clean_password(self):
        v = self.cleaned_data.get('password') or ''
        if not v:
            raise forms.ValidationError('비밀번호를 입력해 주세요.')
        if ' ' in v:
            raise forms.ValidationError('비밀번호에는 공백을 입력할 수 없습니다.')
        if len(v) < 8:
            raise forms.ValidationError('비밀번호는 8자 이상 입력해 주세요.')
        if len(v) > 20:
            raise forms.ValidationError('비밀번호는 20자 이하로 입력해 주세요.')

        # 영문 / 숫자 / 특수문자 중 2가지 이상
        kinds = 0
        if re.search(r'[A-Za-z]', v): kinds += 1
        if re.search(r'\d',         v): kinds += 1
        if re.search(r'[^A-Za-z0-9]', v): kinds += 1
        if kinds < 2:
            raise forms.ValidationError(
                '비밀번호는 영문, 숫자, 특수문자 중 2가지 이상을 포함해 주세요.'
            )
        return v

    # ── 비밀번호 확인 ──
    def clean(self):
        cleaned = super().clean()
        pw  = cleaned.get('password')
        pw2 = cleaned.get('password_check')

        # password 자체가 invalid 인 경우는 이미 errors 에 들어가있어 스킵
        if pw is not None and not self.errors.get('password'):
            if not pw2:
                self.add_error('password_check', '비밀번호 확인을 입력해 주세요.')
            elif pw != pw2:
                self.add_error('password_check', '비밀번호가 일치하지 않습니다.')
        return cleaned

    # ── 소속 ──
    def clean_organization(self):
        v = self.cleaned_data.get('organization')
        if not v:
            raise forms.ValidationError('소속을 선택해 주세요.')
        try:
            org = Organization.objects.get(pk=v)
        except Organization.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 소속입니다.')
        return org

    # ── 권한 (role) ──
    def clean_role(self):
        v = _strip_or_blank(self.cleaned_data.get('role'))
        valid = {choice[0] for choice in User.ROLE_CHOICES}
        if not v:
            raise forms.ValidationError('권한을 선택해 주세요.')
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 권한입니다.')
        return v

    # ── 직위 (선택) ──
    def clean_position_obj(self):
        v = self.cleaned_data.get('position_obj')
        if not v:
            return None
        try:
            return Position.objects.get(pk=v, is_active=True)
        except Position.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 직위입니다.')

    # ── 계정 상태 ──
    def clean_account_status(self):
        v = _strip_or_blank(self.cleaned_data.get('account_status'))
        if not v:
            raise forms.ValidationError('계정 상태를 선택해 주세요.')
        # 등록 시점엔 '잠금' 은 만들지 않음 — '사용' or '비활성' 만 허용
        if v not in (User.ACCOUNT_STATUS_ACTIVE, User.ACCOUNT_STATUS_DISABLED):
            raise forms.ValidationError('계정 상태를 선택해 주세요.')
        return v

    # ── 이메일 ──
    def clean_email(self):
        v = _strip_or_blank(self.cleaned_data.get('email'))
        if not v:
            return ''
        if len(v) > 100:
            raise forms.ValidationError('이메일은 100자 이하로 입력해 주세요.')
        try:
            EmailValidator(message='이메일 형식이 올바르지 않습니다.')(v)
        except forms.ValidationError:
            raise forms.ValidationError('이메일 형식이 올바르지 않습니다.')
        return v

    # ── 연락처 ──
    def clean_phone(self):
        v = _strip_or_blank(self.cleaned_data.get('phone'))
        if not v:
            return ''
        # 숫자/하이픈만 허용
        if not re.fullmatch(r'[\d\-]+', v):
            raise forms.ValidationError('연락처는 숫자만 입력할 수 있습니다.')
        if not PHONE_RE.fullmatch(v):
            raise forms.ValidationError('연락처 형식이 올바르지 않습니다.')
        return v

    # ── DB 반영 ──
    def save(self, *, created_by=None) -> User:
        d = self.cleaned_data
        u = User(
            username    = d['username'],
            first_name  = d['name'],
            email       = d.get('email') or '',
            phone       = d.get('phone') or '',
            role        = d['role'],
            organization= d['organization'],
            department  = d['organization'].name,   # legacy 동기화
            position_obj= d.get('position_obj'),
            position    = d['position_obj'].name if d.get('position_obj') else '',
            is_active   = (d['account_status'] == User.ACCOUNT_STATUS_ACTIVE),
            is_locked   = False,
        )
        u.set_password(d['password'])
        u.save()
        return u


# ═══════════════════════════════════════════════════════════
# 사용자 수정 폼 (아이디/비밀번호 제외 모두 변경 가능)
# ═══════════════════════════════════════════════════════════

class UserUpdateForm(forms.Form):
    """피그마 '사용자 정보 수정' 모달.
    아이디는 read-only, 비밀번호는 별도 '비밀번호 초기화' 버튼.
    """
    name           = forms.CharField(required=False)
    organization   = forms.IntegerField(required=False)
    role           = forms.CharField(required=False)
    position_obj   = forms.IntegerField(required=False)
    account_status = forms.CharField(required=False)
    email          = forms.CharField(required=False)
    phone          = forms.CharField(required=False)

    def __init__(self, *args, instance: User, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    # 사용자명 / 소속 / 권한 / 직위 / 이메일 / 연락처 :
    # 등록 폼과 동일한 validation 재사용
    clean_name         = UserCreateForm.clean_name
    clean_organization = UserCreateForm.clean_organization
    clean_role         = UserCreateForm.clean_role
    clean_position_obj = UserCreateForm.clean_position_obj
    clean_email        = UserCreateForm.clean_email
    clean_phone        = UserCreateForm.clean_phone

    def clean_account_status(self):
        v = _strip_or_blank(self.cleaned_data.get('account_status'))
        valid = (
            User.ACCOUNT_STATUS_ACTIVE,
            User.ACCOUNT_STATUS_LOCKED,
            User.ACCOUNT_STATUS_DISABLED,
        )
        if not v:
            raise forms.ValidationError('계정 상태를 선택해 주세요.')
        if v not in valid:
            raise forms.ValidationError('계정 상태를 선택해 주세요.')
        return v

    def save(self) -> User:
        d = self.cleaned_data
        u = self.instance
        u.first_name  = d['name']
        u.email       = d.get('email') or ''
        u.phone       = d.get('phone') or ''
        u.role        = d['role']
        u.organization= d['organization']
        u.department  = d['organization'].name
        u.position_obj= d.get('position_obj')
        u.position    = d['position_obj'].name if d.get('position_obj') else ''

        status = d['account_status']
        u.is_active = (status != User.ACCOUNT_STATUS_DISABLED)
        u.is_locked = (status == User.ACCOUNT_STATUS_LOCKED)

        u.save()
        return u


# ═══════════════════════════════════════════════════════════
# 조직 등록/수정 폼
# ═══════════════════════════════════════════════════════════

class OrganizationForm(forms.Form):
    name        = forms.CharField(required=False)
    code        = forms.CharField(required=False)
    parent      = forms.IntegerField(required=False)
    description = forms.CharField(required=False)

    def __init__(self, *args, instance: Organization | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance  # 수정 시 None 이 아님

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('부서명을 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('부서명은 50자 이하로 입력해 주세요.')
        return v

    def clean_parent(self):
        v = self.cleaned_data.get('parent')
        if not v:
            return None  # 회사(root) 등록 가능
        try:
            return Organization.objects.get(pk=v)
        except Organization.DoesNotExist:
            raise forms.ValidationError('상위 조직이 유효하지 않습니다.')

    def clean(self):
        cleaned = super().clean()
        name   = cleaned.get('name')
        parent = cleaned.get('parent')
        if name:
            qs = Organization.objects.filter(parent=parent, name=name)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('name', '같은 위치에 동일 부서명이 이미 존재합니다.')
        return cleaned

    def save(self, *, by=None) -> Organization:
        d = self.cleaned_data
        if self.instance and self.instance.pk:
            org = self.instance
        else:
            org = Organization(created_by=by)
        org.name   = d['name']
        org.code   = d.get('code') or ''
        org.parent = d.get('parent')
        org.description = d.get('description') or ''
        org.updated_by = by
        org.save()
        return org


# ═══════════════════════════════════════════════════════════
# 직위 등록/수정 폼
# ═══════════════════════════════════════════════════════════

class PositionForm(forms.Form):
    name       = forms.CharField(required=False)
    sort_order = forms.IntegerField(required=False, min_value=1, max_value=999)
    is_active  = forms.BooleanField(required=False)

    def __init__(self, *args, instance: Position | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('직위명을 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('직위명은 50자 이하로 입력해 주세요.')
        qs = Position.objects.filter(name=v)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('이미 등록된 직위명입니다.')
        return v

    def clean_sort_order(self):
        v = self.cleaned_data.get('sort_order')
        return v if v else 100

    def save(self, *, by=None) -> Position:
        d = self.cleaned_data
        if self.instance and self.instance.pk:
            p = self.instance
        else:
            p = Position(created_by=by)
        p.name       = d['name']
        p.sort_order = d['sort_order']
        p.is_active  = bool(d.get('is_active'))
        p.updated_by = by
        p.save()
        return p


# ═══════════════════════════════════════════════════════════
# 코어 마스터 폼 (공통 코드 / 위험 유형 / 위험 기준 / 임계치)
# ═══════════════════════════════════════════════════════════


UPPER_SNAKE_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')


def _validate_upper_snake(v: str, label: str = '코드'):
    if not UPPER_SNAKE_RE.fullmatch(v):
        raise forms.ValidationError(
            f'{label}는 영문 대문자, 숫자, 언더스코어(_)만 입력할 수 있습니다.'
        )


class _MasterFormBase(forms.Form):
    """code/name/sort_order/is_active 의 공통 패턴.
    상속 클래스에서 model, code_label, name_label 을 override.
    """
    model = None
    code_label = '코드'
    name_label = '명칭'
    code_max_len = 50
    name_max_len = 50

    code        = forms.CharField(required=False)
    name        = forms.CharField(required=False)
    description = forms.CharField(required=False)
    sort_order  = forms.IntegerField(required=False, min_value=1, max_value=99999)
    is_active   = forms.BooleanField(required=False)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_code(self):
        v = _strip_or_blank(self.cleaned_data.get('code'))
        if not v:
            raise forms.ValidationError(f'{self.code_label}를 입력해 주세요.')
        if len(v) > self.code_max_len:
            raise forms.ValidationError(f'{self.code_label}는 {self.code_max_len}자 이하로 입력해 주세요.')
        _validate_upper_snake(v, self.code_label)
        # 중복 검사
        qs = self.model.objects.filter(code=v)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'이미 사용 중인 {self.code_label}입니다.')
        return v

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError(f'{self.name_label}을 입력해 주세요.')
        if len(v) > self.name_max_len:
            raise forms.ValidationError(f'{self.name_label}은 {self.name_max_len}자 이하로 입력해 주세요.')
        return v

    def clean_sort_order(self):
        return self.cleaned_data.get('sort_order') or 100


# ── 공통 코드 ────────────────────────────────────────────
class CodeGroupForm(_MasterFormBase):
    model = CodeGroup
    code_label = '코드 그룹'
    name_label = '그룹명'

    def save(self, *, by=None) -> CodeGroup:
        d = self.cleaned_data
        obj = self.instance or CodeGroup(created_by=by)
        obj.code = d['code']
        obj.name = d['name']
        obj.description = d.get('description') or ''
        obj.sort_order = d['sort_order']
        obj.is_active = bool(d.get('is_active'))
        obj.updated_by = by
        obj.save()
        return obj


class CodeForm(forms.Form):
    """그룹 안의 코드 (group_id 필수)."""
    group_id    = forms.IntegerField(required=False)
    code        = forms.CharField(required=False)
    name        = forms.CharField(required=False)
    description = forms.CharField(required=False)
    sort_order  = forms.IntegerField(required=False, min_value=1, max_value=99999)
    is_active   = forms.BooleanField(required=False)

    def __init__(self, *args, instance: Code | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_group_id(self):
        v = self.cleaned_data.get('group_id')
        if not v:
            raise forms.ValidationError('코드 그룹을 선택해 주세요.')
        try:
            return CodeGroup.objects.get(pk=v)
        except CodeGroup.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 코드 그룹입니다.')

    def clean_code(self):
        v = _strip_or_blank(self.cleaned_data.get('code'))
        if not v:
            raise forms.ValidationError('코드를 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('코드는 50자 이하로 입력해 주세요.')
        return v

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('코드명을 입력해 주세요.')
        if len(v) > 100:
            raise forms.ValidationError('코드명은 100자 이하로 입력해 주세요.')
        return v

    def clean_sort_order(self):
        return self.cleaned_data.get('sort_order') or 100

    def clean(self):
        cleaned = super().clean()
        group = cleaned.get('group_id')
        code = cleaned.get('code')
        if group and code:
            qs = Code.objects.filter(group=group, code=code)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('code', '이 그룹 안에 이미 동일 코드가 존재합니다.')
        return cleaned

    def save(self, *, by=None) -> Code:
        d = self.cleaned_data
        obj = self.instance or Code(created_by=by)
        obj.group = d['group_id']
        obj.code = d['code']
        obj.name = d['name']
        obj.description = d.get('description') or ''
        obj.sort_order = d['sort_order']
        obj.is_active = bool(d.get('is_active'))
        obj.updated_by = by
        obj.save()
        return obj


# ── 위험 유형 ────────────────────────────────────────────
class RiskCategoryForm(_MasterFormBase):
    model = RiskCategory
    code_label = '분류 코드'
    name_label = '분류명'

    applies_to = forms.CharField(required=False)   # CSV

    def clean_applies_to(self):
        v = _strip_or_blank(self.cleaned_data.get('applies_to'))
        valid = {'realtime', 'event', 'alarm'}
        items = [s for s in v.split(',') if s.strip()]
        bad = [s for s in items if s not in valid]
        if bad:
            raise forms.ValidationError(f'유효하지 않은 반영 범위: {bad}')
        return ','.join(items)

    def save(self, *, by=None) -> RiskCategory:
        d = self.cleaned_data
        obj = self.instance or RiskCategory(created_by=by)
        obj.code = d['code']
        obj.name = d['name']
        obj.description = d.get('description') or ''
        obj.applies_to = d.get('applies_to') or ''
        obj.sort_order = d['sort_order']
        obj.is_active = bool(d.get('is_active'))
        obj.updated_by = by
        obj.save()
        return obj


class RiskTypeForm(forms.Form):
    category_id = forms.IntegerField(required=False)
    code        = forms.CharField(required=False)
    name        = forms.CharField(required=False)
    description = forms.CharField(required=False)
    show_on_map = forms.BooleanField(required=False)
    sort_order  = forms.IntegerField(required=False, min_value=1, max_value=99999)
    is_active   = forms.BooleanField(required=False)

    def __init__(self, *args, instance: RiskType | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_category_id(self):
        v = self.cleaned_data.get('category_id')
        if not v:
            raise forms.ValidationError('위험 분류를 선택해 주세요.')
        try:
            return RiskCategory.objects.get(pk=v)
        except RiskCategory.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 위험 분류입니다.')

    def clean_code(self):
        v = _strip_or_blank(self.cleaned_data.get('code'))
        if not v:
            raise forms.ValidationError('유형 코드를 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('유형 코드는 50자 이하로 입력해 주세요.')
        return v

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('유형명을 입력해 주세요.')
        if len(v) > 100:
            raise forms.ValidationError('유형명은 100자 이하로 입력해 주세요.')
        return v

    def clean_sort_order(self):
        return self.cleaned_data.get('sort_order') or 100

    def clean(self):
        cleaned = super().clean()
        cat = cleaned.get('category_id')
        code = cleaned.get('code')
        if cat and code:
            qs = RiskType.objects.filter(category=cat, code=code)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('code', '이 분류 안에 이미 동일 유형 코드가 존재합니다.')
        return cleaned

    def save(self, *, by=None) -> RiskType:
        d = self.cleaned_data
        obj = self.instance or RiskType(created_by=by)
        obj.category = d['category_id']
        obj.code = d['code']
        obj.name = d['name']
        obj.description = d.get('description') or ''
        obj.show_on_map = bool(d.get('show_on_map'))
        obj.sort_order = d['sort_order']
        obj.is_active = bool(d.get('is_active'))
        obj.updated_by = by
        obj.save()
        return obj


# ── 위험 기준 (알람 단계) ─────────────────────────────────
class AlarmLevelForm(forms.Form):
    code        = forms.CharField(required=False)
    name        = forms.CharField(required=False)
    color       = forms.CharField(required=False)
    intensity   = forms.CharField(required=False)
    priority    = forms.IntegerField(required=False, min_value=1, max_value=999)
    description = forms.CharField(required=False)
    is_active   = forms.BooleanField(required=False)

    def __init__(self, *args, instance: AlarmLevel | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_code(self):
        v = _strip_or_blank(self.cleaned_data.get('code'))
        if not v:
            raise forms.ValidationError('단계 코드를 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('단계 코드는 50자 이하로 입력해 주세요.')
        _validate_upper_snake(v, '단계 코드')
        qs = AlarmLevel.objects.filter(code=v)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('이미 등록된 단계 코드입니다.')
        return v

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('단계명을 입력해 주세요.')
        return v

    def clean_color(self):
        v = _strip_or_blank(self.cleaned_data.get('color'))
        valid = {c[0] for c in ALARM_COLOR_CHOICES}
        if not v:
            raise forms.ValidationError('표시 색상을 선택해 주세요.')
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 색상입니다.')
        return v

    def clean_intensity(self):
        v = _strip_or_blank(self.cleaned_data.get('intensity'))
        valid = {c[0] for c in ALARM_INTENSITY_CHOICES}
        if not v:
            raise forms.ValidationError('알림 강도를 선택해 주세요.')
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 알림 강도입니다.')
        return v

    def clean_priority(self):
        v = self.cleaned_data.get('priority')
        if v is None:
            raise forms.ValidationError('이벤트 우선순위를 입력해 주세요.')
        return v

    def save(self, *, by=None) -> AlarmLevel:
        d = self.cleaned_data
        obj = self.instance or AlarmLevel(created_by=by)
        obj.code = d['code']
        obj.name = d['name']
        obj.color = d['color']
        obj.intensity = d['intensity']
        obj.priority = d['priority']
        obj.description = d.get('description') or ''
        obj.is_active = bool(d.get('is_active'))
        obj.updated_by = by
        obj.save()
        return obj


# ── 임계치 ────────────────────────────────────────────────
class ThresholdCategoryForm(_MasterFormBase):
    model = ThresholdCategory
    code_label = '분류 코드'
    name_label = '분류명'

    applies_to = forms.CharField(required=False)

    def clean_applies_to(self):
        v = _strip_or_blank(self.cleaned_data.get('applies_to'))
        valid = {'realtime', 'ai_predict', 'alarm'}
        items = [s for s in v.split(',') if s.strip()]
        bad = [s for s in items if s not in valid]
        if bad:
            raise forms.ValidationError(f'유효하지 않은 반영 범위: {bad}')
        return ','.join(items)

    def save(self, *, by=None) -> ThresholdCategory:
        d = self.cleaned_data
        obj = self.instance or ThresholdCategory(created_by=by)
        obj.code = d['code']
        obj.name = d['name']
        obj.description = d.get('description') or ''
        obj.applies_to = d.get('applies_to') or ''
        obj.sort_order = d['sort_order']
        obj.is_active = bool(d.get('is_active'))
        obj.updated_by = by
        obj.save()
        return obj


class ThresholdForm(forms.Form):
    category_id = forms.IntegerField(required=False)
    item_code   = forms.CharField(required=False)
    item_name   = forms.CharField(required=False)
    unit        = forms.CharField(required=False)
    operator    = forms.CharField(required=False)
    caution_value = forms.FloatField(required=False)
    danger_value  = forms.FloatField(required=False)
    is_active   = forms.BooleanField(required=False)
    applies_to  = forms.CharField(required=False)
    description = forms.CharField(required=False)

    def __init__(self, *args, instance: Threshold | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_category_id(self):
        v = self.cleaned_data.get('category_id')
        if not v:
            raise forms.ValidationError('임계치 분류를 선택해 주세요.')
        try:
            return ThresholdCategory.objects.get(pk=v)
        except ThresholdCategory.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 임계치 분류입니다.')

    def clean_item_code(self):
        v = _strip_or_blank(self.cleaned_data.get('item_code'))
        if not v:
            raise forms.ValidationError('측정 항목 코드를 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('측정 항목 코드는 50자 이하로 입력해 주세요.')
        return v

    def clean_item_name(self):
        v = _strip_or_blank(self.cleaned_data.get('item_name'))
        if not v:
            raise forms.ValidationError('측정 항목명을 입력해 주세요.')
        return v

    def clean_unit(self):
        v = _strip_or_blank(self.cleaned_data.get('unit'))
        if not v:
            raise forms.ValidationError('단위를 입력해 주세요.')
        return v

    def clean_operator(self):
        v = _strip_or_blank(self.cleaned_data.get('operator'))
        valid = {c[0] for c in THRESHOLD_OPERATOR_CHOICES}
        if not v:
            raise forms.ValidationError('판단 조건을 선택해 주세요.')
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 판단 조건입니다.')
        return v

    def clean_caution_value(self):
        v = self.cleaned_data.get('caution_value')
        if v is None:
            raise forms.ValidationError('주의값을 입력해 주세요.')
        return v

    def clean_danger_value(self):
        v = self.cleaned_data.get('danger_value')
        if v is None:
            raise forms.ValidationError('위험값을 입력해 주세요.')
        return v

    def clean_applies_to(self):
        v = _strip_or_blank(self.cleaned_data.get('applies_to'))
        valid = {'realtime', 'ai_predict', 'alarm'}
        items = [s for s in v.split(',') if s.strip()]
        bad = [s for s in items if s not in valid]
        if bad:
            raise forms.ValidationError(f'유효하지 않은 반영 범위: {bad}')
        if not items:
            raise forms.ValidationError('반영 범위를 1개 이상 선택해 주세요.')
        return ','.join(items)

    def clean(self):
        cleaned = super().clean()
        cat = cleaned.get('category_id')
        ic = cleaned.get('item_code')
        op = cleaned.get('operator')
        cv = cleaned.get('caution_value')
        dv = cleaned.get('danger_value')

        # over: 위험값 > 주의값.  under: 위험값 < 주의값.
        if op and cv is not None and dv is not None:
            if op == 'over' and dv <= cv:
                self.add_error('danger_value', '판단 조건 "초과" 일 때 위험값은 주의값보다 커야 합니다.')
            elif op == 'under' and dv >= cv:
                self.add_error('danger_value', '판단 조건 "이하" 일 때 위험값은 주의값보다 작아야 합니다.')

        if cat and ic:
            qs = Threshold.objects.filter(category=cat, item_code=ic)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('item_code', '이 분류 안에 이미 동일 측정 항목이 존재합니다.')
        return cleaned

    def save(self, *, by=None) -> Threshold:
        d = self.cleaned_data
        obj = self.instance or Threshold(created_by=by)
        obj.category = d['category_id']
        obj.item_code = d['item_code']
        obj.item_name = d['item_name']
        obj.unit = d['unit']
        obj.operator = d['operator']
        obj.caution_value = d['caution_value']
        obj.danger_value = d['danger_value']
        obj.is_active = bool(d.get('is_active'))
        obj.applies_to = d['applies_to']
        obj.description = d.get('description') or ''
        obj.updated_by = by
        obj.save()
        return obj


# ═══════════════════════════════════════════════════════════
# 알림 정책 / 메뉴 권한 폼
# ═══════════════════════════════════════════════════════════



class NotificationPolicyForm(forms.Form):
    """알림 정책 등록/수정 폼.

    Validation 핵심:
      - code: UPPER_SNAKE, 중복 금지
      - risk_category, alarm_level: PK 유효성
      - channels: 1개 이상 선택
      - recipients: 1개 이상 선택 (특수 토큰 또는 group:id / role:code)
    """
    code           = forms.CharField(required=False)
    name           = forms.CharField(required=False)
    description    = forms.CharField(required=False)
    risk_category  = forms.IntegerField(required=False)
    alarm_level    = forms.IntegerField(required=False)
    channels_csv   = forms.CharField(required=False)
    recipients_csv = forms.CharField(required=False)
    message_template = forms.CharField(required=False)
    sort_order     = forms.IntegerField(required=False, min_value=1, max_value=99999)
    is_active      = forms.BooleanField(required=False)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_code(self):
        v = _strip_or_blank(self.cleaned_data.get('code'))
        if not v:
            raise forms.ValidationError('정책 코드를 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('정책 코드는 50자 이하로 입력해 주세요.')
        _validate_upper_snake(v, '정책 코드')
        qs = NotificationPolicy.objects.filter(code=v)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('이미 사용 중인 정책 코드입니다.')
        return v

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('정책명을 입력해 주세요.')
        if len(v) > 100:
            raise forms.ValidationError('정책명은 100자 이하로 입력해 주세요.')
        return v

    def clean_risk_category(self):
        v = self.cleaned_data.get('risk_category')
        if not v:
            raise forms.ValidationError('적용 위험 분류를 선택해 주세요.')
        try:
            return RiskCategory.objects.get(pk=v)
        except RiskCategory.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 위험 분류입니다.')

    def clean_alarm_level(self):
        v = self.cleaned_data.get('alarm_level')
        if not v:
            raise forms.ValidationError('적용 알람 단계를 선택해 주세요.')
        try:
            return AlarmLevel.objects.get(pk=v)
        except AlarmLevel.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 알람 단계입니다.')

    def clean_channels_csv(self):
        v = _strip_or_blank(self.cleaned_data.get('channels_csv'))
        valid = {c[0] for c in NOTIFICATION_CHANNEL_CHOICES}
        items = [s for s in v.split(',') if s.strip()]
        bad = [s for s in items if s not in valid]
        if bad:
            raise forms.ValidationError(f'유효하지 않은 채널: {bad}')
        if not items:
            raise forms.ValidationError('발송 채널을 1개 이상 선택해 주세요.')
        return ','.join(items)

    def clean_recipients_csv(self):
        v = _strip_or_blank(self.cleaned_data.get('recipients_csv'))
        items = [s for s in v.split(',') if s.strip()]
        if not items:
            raise forms.ValidationError('수신 대상을 1개 이상 선택해 주세요.')
        # 토큰 검증 — all_users / leaders / group:<id> / role:<code>
        valid_roles = {'super_admin', 'admin', 'operator'}
        for token in items:
            if token in ('all_users', 'leaders'):
                continue
            if token.startswith('group:'):
                org_id = token[6:]
                if not org_id.isdigit():
                    raise forms.ValidationError(f'그룹 ID 형식 오류: {token}')
                if not Organization.objects.filter(pk=int(org_id)).exists():
                    raise forms.ValidationError(f'존재하지 않는 조직: {token}')
                continue
            if token.startswith('role:'):
                role = token[5:]
                if role not in valid_roles:
                    raise forms.ValidationError(f'유효하지 않은 역할 토큰: {token}')
                continue
            raise forms.ValidationError(f'유효하지 않은 수신 대상 토큰: {token}')
        return ','.join(items)

    def clean_sort_order(self):
        return self.cleaned_data.get('sort_order') or 100

    def save(self, *, by=None) -> NotificationPolicy:
        d = self.cleaned_data
        obj = self.instance or NotificationPolicy(created_by=by)
        obj.code = d['code']
        obj.name = d['name']
        obj.description = d.get('description') or ''
        obj.risk_category = d['risk_category']
        obj.alarm_level = d['alarm_level']
        obj.channels_csv = d['channels_csv']
        obj.recipients_csv = d['recipients_csv']
        obj.message_template = d.get('message_template') or ''
        obj.sort_order = d['sort_order']
        obj.is_active = bool(d.get('is_active'))
        obj.updated_by = by
        obj.save()
        return obj


class MenuPermissionUpdateForm(forms.Form):
    """단일 (role, menu_code) 권한 토글 폼 — bulk update 용."""
    role = forms.CharField(required=False)
    menu_code = forms.CharField(required=False)
    is_visible = forms.BooleanField(required=False)
    is_writable = forms.BooleanField(required=False)

    def clean_role(self):
        v = _strip_or_blank(self.cleaned_data.get('role'))
        if v not in {'admin', 'operator'}:
            raise forms.ValidationError('역할은 admin 또는 operator 만 변경 가능합니다.')
        return v

    def clean_menu_code(self):
        v = _strip_or_blank(self.cleaned_data.get('menu_code'))
        valid = {c[0] for c in MENU_CODE_CHOICES}
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 메뉴 코드입니다.')
        return v


# ═══════════════════════════════════════════════════════════
# 설비/장비 / 지도/지오펜스 / 운영데이터 / 공지사항 폼
# ═══════════════════════════════════════════════════════════



class DeviceForm(forms.Form):
    """장비 등록/수정.
    Validation: device_id 영문/숫자/하이픈/언더스코어, 좌표 정수, 센서타입 유효."""
    device_id   = forms.CharField(required=False)
    device_name = forms.CharField(required=False)
    sensor_type = forms.CharField(required=False)
    x           = forms.FloatField(required=False)
    y           = forms.FloatField(required=False)
    is_active   = forms.BooleanField(required=False)
    geofence_id = forms.IntegerField(required=False)
    last_value_unit = forms.CharField(required=False)

    DEVICE_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_device_id(self):
        v = _strip_or_blank(self.cleaned_data.get('device_id'))
        if not v:
            raise forms.ValidationError('장비 ID를 입력해 주세요.')
        if len(v) > 50:
            raise forms.ValidationError('장비 ID는 50자 이하로 입력해 주세요.')
        if not self.DEVICE_ID_RE.fullmatch(v):
            raise forms.ValidationError('장비 ID는 영문, 숫자, -, _ 만 입력할 수 있습니다.')
        qs = Device.objects.filter(device_id=v)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('이미 사용 중인 장비 ID입니다.')
        return v

    def clean_device_name(self):
        v = _strip_or_blank(self.cleaned_data.get('device_name'))
        if not v:
            raise forms.ValidationError('장비명을 입력해 주세요.')
        if len(v) > 100:
            raise forms.ValidationError('장비명은 100자 이하로 입력해 주세요.')
        return v

    def clean_sensor_type(self):
        v = _strip_or_blank(self.cleaned_data.get('sensor_type'))
        valid = {c[0] for c in DEVICE_SENSOR_TYPE_CHOICES}
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 센서 타입입니다.')
        return v

    def clean_x(self):
        v = self.cleaned_data.get('x')
        if v is None:
            raise forms.ValidationError('X 좌표를 입력해 주세요.')
        return v

    def clean_y(self):
        v = self.cleaned_data.get('y')
        if v is None:
            raise forms.ValidationError('Y 좌표를 입력해 주세요.')
        return v

    def clean_geofence_id(self):
        v = self.cleaned_data.get('geofence_id')
        if not v:
            return None
        try:
            return GeoFence.objects.get(pk=v)
        except GeoFence.DoesNotExist:
            raise forms.ValidationError('유효하지 않은 지오펜스입니다.')

    def save(self, *, by=None) -> Device:
        d = self.cleaned_data
        is_new = self.instance is None or self.instance.pk is None
        obj = self.instance or Device()

        # 변경 추적용 — 기존 값 캡처
        old_values = {}
        if not is_new:
            old_values = {
                'device_name': obj.device_name,
                'sensor_type': obj.sensor_type,
                'x': obj.x, 'y': obj.y,
                'is_active': obj.is_active,
                'geofence_id': obj.geofence_id,
            }

        obj.device_id = d['device_id']
        obj.device_name = d['device_name']
        obj.sensor_type = d['sensor_type']
        obj.x = d['x']
        obj.y = d['y']
        obj.is_active = bool(d.get('is_active'))
        obj.last_value_unit = d.get('last_value_unit') or ''

        # 지오펜스 — 명시 선택이 우선, 없으면 좌표 기준 자동 매핑 시도
        if d.get('geofence_id'):
            obj.geofence = d['geofence_id']
        elif obj.geofence_id is None:
            from .geo_utils import find_containing_geofence
            from geofence.models import GeoFence
            active_fences = GeoFence.objects.filter(is_active=True)
            matched = find_containing_geofence(obj.x, obj.y, active_fences)
            if matched:
                obj.geofence = matched
        obj.save()

        # v6 — DeviceHistory 자동 기록
        try:
            from .audit import write_device_history
            if is_new:
                write_device_history(obj, 'create', changes={
                    'device_id': [None, obj.device_id],
                    'device_name': [None, obj.device_name],
                    'xy': [None, [obj.x, obj.y]],
                })
            else:
                changes = {}
                for field, old_val in old_values.items():
                    new_val = getattr(obj, field, None)
                    if field == 'geofence_id':
                        if old_val != new_val:
                            changes['geofence'] = [old_val, new_val]
                    elif old_val != new_val:
                        changes[field] = [old_val, new_val]
                if changes:
                    write_device_history(obj, 'update', changes=changes)
        except Exception:
            pass  # history 실패는 본 작업에 영향 없음

        return obj


class GeoFenceForm(forms.Form):
    """지오펜스 등록/수정. polygon 은 [[x,y], ...] JSON."""
    name        = forms.CharField(required=False)
    zone_type   = forms.CharField(required=False)
    risk_level  = forms.CharField(required=False)
    description = forms.CharField(required=False)
    polygon_json = forms.CharField(required=False)
    is_active   = forms.BooleanField(required=False)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_name(self):
        v = _strip_or_blank(self.cleaned_data.get('name'))
        if not v:
            raise forms.ValidationError('지오펜스명을 입력해 주세요.')
        if len(v) > 100:
            raise forms.ValidationError('지오펜스명은 100자 이하로 입력해 주세요.')
        return v

    def clean_zone_type(self):
        v = _strip_or_blank(self.cleaned_data.get('zone_type'))
        valid = {c[0] for c in ZONE_TYPE_CHOICES}
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 구역 유형입니다.')
        return v

    def clean_risk_level(self):
        v = _strip_or_blank(self.cleaned_data.get('risk_level'))
        valid = {c[0] for c in RISK_LEVEL_CHOICES}
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 위험 등급입니다.')
        return v

    def clean_polygon_json(self):
        v = _strip_or_blank(self.cleaned_data.get('polygon_json'))
        if not v:
            raise forms.ValidationError('폴리곤 좌표를 입력해 주세요.')
        import json as _json
        try:
            poly = _json.loads(v)
        except (ValueError, _json.JSONDecodeError):
            raise forms.ValidationError('폴리곤 좌표는 JSON 배열 형식이어야 합니다.')
        if not isinstance(poly, list) or len(poly) < 3:
            raise forms.ValidationError('폴리곤은 최소 3개의 좌표가 필요합니다.')
        for pt in poly:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise forms.ValidationError('각 좌표는 [x, y] 형식이어야 합니다.')
            try:
                float(pt[0]); float(pt[1])
            except (TypeError, ValueError):
                raise forms.ValidationError('좌표값은 숫자여야 합니다.')
        return poly

    def save(self) -> GeoFence:
        d = self.cleaned_data
        obj = self.instance or GeoFence()
        obj.name = d['name']
        obj.zone_type = d['zone_type']
        obj.risk_level = d['risk_level']
        obj.description = d.get('description') or ''
        obj.polygon = d['polygon_json']
        obj.is_active = bool(d.get('is_active'))
        obj.save()
        return obj


class DataRetentionForm(forms.Form):
    """보관 정책 수정 폼. target 은 read-only (시드 5종 고정)."""
    retention_days = forms.IntegerField(required=False, min_value=1, max_value=3650)
    is_active      = forms.BooleanField(required=False)
    description    = forms.CharField(required=False)

    def __init__(self, *args, instance: DataRetentionPolicy, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_retention_days(self):
        v = self.cleaned_data.get('retention_days')
        if v is None:
            raise forms.ValidationError('보관 기간을 입력해 주세요.')
        if v < 1:
            raise forms.ValidationError('보관 기간은 1일 이상이어야 합니다.')
        if v > 3650:
            raise forms.ValidationError('보관 기간은 3650일(10년) 이하여야 합니다.')
        return v

    def save(self, *, by=None) -> DataRetentionPolicy:
        d = self.cleaned_data
        p = self.instance
        p.retention_days = d['retention_days']
        p.is_active = bool(d.get('is_active'))
        p.description = d.get('description') or ''
        p.updated_by = by
        p.save()
        return p


class NoticeForm(forms.Form):
    """공지사항 등록/수정."""
    title          = forms.CharField(required=False)
    category       = forms.CharField(required=False)
    content        = forms.CharField(required=False)
    is_pinned      = forms.BooleanField(required=False)
    is_published   = forms.BooleanField(required=False)
    published_from = forms.CharField(required=False)
    published_to   = forms.CharField(required=False)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_title(self):
        v = _strip_or_blank(self.cleaned_data.get('title'))
        if not v:
            raise forms.ValidationError('제목을 입력해 주세요.')
        if len(v) > 200:
            raise forms.ValidationError('제목은 200자 이하로 입력해 주세요.')
        return v

    def clean_category(self):
        v = _strip_or_blank(self.cleaned_data.get('category'))
        valid = {c[0] for c in NOTICE_CATEGORY_CHOICES}
        if v not in valid:
            raise forms.ValidationError('유효하지 않은 카테고리입니다.')
        return v

    def clean_content(self):
        v = _strip_or_blank(self.cleaned_data.get('content'))
        if not v:
            raise forms.ValidationError('내용을 입력해 주세요.')
        return v

    def _parse_dt(self, raw, field_name):
        """yyyy-mm-dd 또는 yyyy-mm-ddTHH:MM (datetime-local) 둘 다 지원."""
        if not raw:
            return None
        from datetime import datetime as _dt
        from django.utils import timezone as _tz
        for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return _tz.make_aware(_dt.strptime(raw, fmt))
            except ValueError:
                continue
        raise forms.ValidationError('날짜 형식이 올바르지 않습니다 (예: 2026-05-01T09:00).')

    def clean_published_from(self):
        return self._parse_dt(_strip_or_blank(self.cleaned_data.get('published_from')), 'from')

    def clean_published_to(self):
        return self._parse_dt(_strip_or_blank(self.cleaned_data.get('published_to')), 'to')

    def clean(self):
        cleaned = super().clean()
        f, t = cleaned.get('published_from'), cleaned.get('published_to')
        if f and t and f > t:
            self.add_error('published_to', '게시 종료일은 시작일 이후여야 합니다.')
        return cleaned

    def save(self, *, by=None) -> Notice:
        d = self.cleaned_data
        obj = self.instance or Notice(created_by=by)
        obj.title = d['title']
        obj.category = d['category']
        obj.content = d['content']
        obj.is_pinned = bool(d.get('is_pinned'))
        obj.is_published = bool(d.get('is_published'))
        obj.published_from = d.get('published_from')
        obj.published_to = d.get('published_to')
        obj.updated_by = by
        obj.save()
        return obj
