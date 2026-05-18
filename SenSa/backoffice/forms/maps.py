"""
backoffice/forms/maps.py — 지도 관련 (지오펜스 + 평면도 이미지) 폼.

  - GeoFenceForm  — 지오펜스 등록/수정
  - MapImageForm  — v7 평면도 이미지 (ModelForm)
"""
from django import forms

from dashboard.models import MapImage
from geofence.models import GeoFence, ZONE_TYPE_CHOICES, RISK_LEVEL_CHOICES

from ._common import _strip_or_blank


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


# ═══════════════════════════════════════════════════════════
# v7: 평면도 이미지 (MapImage) 관리
# ═══════════════════════════════════════════════════════════

class MapImageForm(forms.ModelForm):
    """평면도 이미지 등록/수정.

    동작:
      - 신규 등록 시 image 필수, 이름은 미입력 시 파일명에서 자동 생성
      - 이미지 새로 업로드 시 width/height 자동 추출 (Pillow)
      - sort_order 음수 불가
    """

    class Meta:
        model = MapImage
        fields = ['image', 'name', 'sort_order', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 신규 등록 시만 image 필수, 수정 시는 선택
        self.fields['image'].required = self.instance.pk is None
        self.fields['name'].required = False

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            img = self.cleaned_data.get('image')
            if img and hasattr(img, 'name'):
                # 파일명에서 확장자 제거
                base = img.name.rsplit('/', 1)[-1]
                name = base.rsplit('.', 1)[0][:100] or '평면도'
            else:
                name = '평면도'
        if len(name) > 100:
            raise forms.ValidationError('지도 이름은 100자 이하로 입력해 주세요.')
        return name

    def clean_sort_order(self):
        v = self.cleaned_data.get('sort_order')
        if v is None:
            v = 0
        if v < 0:
            raise forms.ValidationError('순서는 0 이상이어야 합니다.')
        return v

    def save(self, commit=True):
        instance = super().save(commit=False)
        # 새 이미지가 업로드된 경우 width/height 자동 추출
        new_image = self.cleaned_data.get('image')
        # ImageField 의 변경 감지 — 파일 객체에 read 가 있으면 새 업로드
        if new_image and hasattr(new_image, 'read'):
            try:
                from PIL import Image as PILImage
                pil = PILImage.open(new_image)
                instance.width = pil.width
                instance.height = pil.height
            except Exception:
                # Pillow 실패 시 0 유지 — 운영자가 수동 입력 가능
                pass
        if commit:
            instance.save()
        return instance
