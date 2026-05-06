"""
backoffice/forms/notices.py — 공지사항 등록/수정 폼.
"""
from django import forms

from ..models import Notice, NOTICE_CATEGORY_CHOICES
from ._common import _strip_or_blank


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
