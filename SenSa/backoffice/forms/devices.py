"""
backoffice/forms/devices.py — 설비/장비 등록/수정 폼.

DeviceForm 의 save() 는 자동으로:
  1. 좌표 기준 지오펜스 매핑 (선택)
  2. v6 DeviceHistory 변경 추적 기록
"""
import re

from django import forms

from devices.models import Device, SENSOR_TYPE_CHOICES as DEVICE_SENSOR_TYPE_CHOICES
from geofence.models import GeoFence

from ._common import _strip_or_blank


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
            from ..geo_utils import find_containing_geofence
            active_fences = GeoFence.objects.filter(is_active=True)
            matched = find_containing_geofence(obj.x, obj.y, active_fences)
            if matched:
                obj.geofence = matched
        obj.save()

        # v6 — DeviceHistory 자동 기록
        try:
            from ..audit import write_device_history
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
