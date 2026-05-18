"""
backoffice/forms/notifications.py — 알림 정책 + 메뉴 권한 폼.

  - NotificationPolicyForm     — 알림 정책 등록/수정 (위험 분류 × 알람 단계 매트릭스)
  - MenuPermissionUpdateForm   — 역할별 메뉴 권한 토글
"""
from django import forms

from ..models import (
    NotificationPolicy,
    RiskCategory, AlarmLevel, Organization,
    NOTIFICATION_CHANNEL_CHOICES, MENU_CODE_CHOICES,
)
from ._common import _strip_or_blank, _validate_upper_snake


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
