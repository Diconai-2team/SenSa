"""
backoffice/forms/_common.py — 모든 폼 모듈이 공유하는 정규식/헬퍼/베이스 클래스.

분리 이력 (Phase 2):
  원래 backoffice/forms.py 에 흩어져 있던 공통 요소들을 한 곳에 모음.
  - regex 들 (USERNAME_RE 등)         (원본 line 55-57)
  - _strip_or_blank 헬퍼              (원본 line 60-61)
  - UPPER_SNAKE_RE + _validate_upper_snake  (원본 line 409-416)
  - _MasterFormBase 추상 폼            (원본 line 419-463)

다른 폼 모듈은 `from ._common import _strip_or_blank, _MasterFormBase` 등으로 사용.
"""
import re

from django import forms


# ═══════════════════════════════════════════════════════════
# 정규식 — 사용자/조직 폼에서 공유
# ═══════════════════════════════════════════════════════════

USERNAME_RE = re.compile(r'^[A-Za-z0-9가-힣]+$')        # 한글/영문/숫자만
LOGIN_ID_RE = re.compile(r'^[A-Za-z0-9]+$')             # 영문/숫자만
PHONE_RE    = re.compile(r'^\d{2,4}-?\d{3,4}-?\d{4}$')


def _strip_or_blank(value: str | None) -> str:
    return (value or '').strip()


# ═══════════════════════════════════════════════════════════
# 마스터 코드 형식 검증 — masters.py 의 모든 *Form 이 공유
# ═══════════════════════════════════════════════════════════

UPPER_SNAKE_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')


def _validate_upper_snake(v: str, label: str = '코드'):
    if not UPPER_SNAKE_RE.fullmatch(v):
        raise forms.ValidationError(
            f'{label}는 영문 대문자, 숫자, 언더스코어(_)만 입력할 수 있습니다.'
        )


# ═══════════════════════════════════════════════════════════
# 마스터 폼 공통 부모 — masters.py 의 7개 폼 중 3개가 상속
# (CodeGroupForm, RiskCategoryForm, ThresholdCategoryForm)
# ═══════════════════════════════════════════════════════════

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
