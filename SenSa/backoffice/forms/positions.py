"""
backoffice/forms/positions.py — 직위 등록·수정 폼.
"""
from django import forms

from ..models import Position
from ._common import _strip_or_blank


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
