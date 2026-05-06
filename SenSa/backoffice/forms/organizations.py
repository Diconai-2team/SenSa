"""
backoffice/forms/organizations.py — 조직(부서/회사) 등록·수정 폼.
"""
from django import forms

from ..models import Organization
from ._common import _strip_or_blank


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
