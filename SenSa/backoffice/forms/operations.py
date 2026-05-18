"""
backoffice/forms/operations.py — 운영 데이터 보관 정책 폼.
"""
from django import forms

from ..models import DataRetentionPolicy


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
