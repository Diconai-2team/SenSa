"""
backoffice/forms/masters.py — 코어 마스터 (참조 데이터) 폼.

7개 폼 클래스:
  공통 코드:    CodeGroupForm, CodeForm
  위험 유형:    RiskCategoryForm, RiskTypeForm
  위험 기준:    AlarmLevelForm
  임계치:       ThresholdCategoryForm, ThresholdForm

3개 (CodeGroupForm, RiskCategoryForm, ThresholdCategoryForm) 는
_MasterFormBase 를 상속하여 code/name/sort_order/is_active 패턴 공유.
"""
from django import forms

from ..models import (
    CodeGroup, Code,
    RiskCategory, RiskType, AlarmLevel,
    ThresholdCategory, Threshold,
    ALARM_COLOR_CHOICES, ALARM_INTENSITY_CHOICES,
    THRESHOLD_OPERATOR_CHOICES,
)
from ._common import _strip_or_blank, _validate_upper_snake, _MasterFormBase


# ═══════════════════════════════════════════════════════════
# 공통 코드
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# 위험 유형
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# 위험 기준 (알람 단계)
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# 임계치
# ═══════════════════════════════════════════════════════════

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
