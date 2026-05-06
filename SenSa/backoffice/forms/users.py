"""
backoffice/forms/users.py — 사용자 등록/수정 폼.

  - UserCreateForm  — 피그마 '사용자 등록' 모달 validation 명세 그대로
  - UserUpdateForm  — 피그마 '사용자 정보 수정' 모달 (아이디/비밀번호 제외)

UserUpdateForm 의 clean_* 메서드 중 절반은 UserCreateForm 의 것을 그대로 재사용
(같은 validation 규칙). 한 파일에 둬야 이 재사용이 자연스러움.
"""
import re

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import EmailValidator

from ..models import Organization, Position
from ._common import LOGIN_ID_RE, PHONE_RE, USERNAME_RE, _strip_or_blank


User = get_user_model()


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
