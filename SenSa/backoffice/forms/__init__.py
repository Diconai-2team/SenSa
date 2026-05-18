"""
backoffice/forms/ — 백오피스 폼 패키지.

[Phase 2 분리 — 2026-05-06]
  원본: 단일 backoffice/forms.py (1,394줄, 19개 폼 클래스)
  현행: 도메인별 10개 모듈 (이 파일 + _common 제외)

호환성:
  외부 코드의 `from backoffice.forms import UserCreateForm` 등 그대로 동작.
  views/ 패키지 (Phase 1) 의 모든 form import 도 그대로 동작.

모듈 매핑 (views/ 와 1:1):
  _common.py        — 공통 regex/헬퍼 + _MasterFormBase
  users.py          — UserCreateForm, UserUpdateForm
  organizations.py  — OrganizationForm
  positions.py      — PositionForm
  masters.py        — CodeGroupForm, CodeForm, RiskCategoryForm, RiskTypeForm,
                      AlarmLevelForm, ThresholdCategoryForm, ThresholdForm  (7개)
  notifications.py  — NotificationPolicyForm, MenuPermissionUpdateForm
  devices.py        — DeviceForm
  maps.py           — GeoFenceForm, MapImageForm
  operations.py     — DataRetentionForm
  notices.py        — NoticeForm
"""
# ─── users ───
from .users import UserCreateForm, UserUpdateForm

# ─── organizations ───
from .organizations import OrganizationForm

# ─── positions ───
from .positions import PositionForm

# ─── masters (codes / risks / alarm levels / thresholds) ───
from .masters import (
    CodeGroupForm, CodeForm,
    RiskCategoryForm, RiskTypeForm,
    AlarmLevelForm,
    ThresholdCategoryForm, ThresholdForm,
)

# ─── notifications + menu permissions ───
from .notifications import NotificationPolicyForm, MenuPermissionUpdateForm

# ─── devices ───
from .devices import DeviceForm

# ─── maps (geofence + map image v7) ───
from .maps import GeoFenceForm, MapImageForm

# ─── operations (retention policy) ───
from .operations import DataRetentionForm

# ─── notices ───
from .notices import NoticeForm


__all__ = [
    # users
    'UserCreateForm', 'UserUpdateForm',
    # organizations
    'OrganizationForm',
    # positions
    'PositionForm',
    # masters
    'CodeGroupForm', 'CodeForm',
    'RiskCategoryForm', 'RiskTypeForm',
    'AlarmLevelForm',
    'ThresholdCategoryForm', 'ThresholdForm',
    # notifications + menu
    'NotificationPolicyForm', 'MenuPermissionUpdateForm',
    # devices
    'DeviceForm',
    # maps
    'GeoFenceForm', 'MapImageForm',
    # operations
    'DataRetentionForm',
    # notices
    'NoticeForm',
]
