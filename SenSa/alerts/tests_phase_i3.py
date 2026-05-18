"""
alerts/tests_phase_i3.py — Phase I-3 검증 테스트.

usage:
    python manage.py test alerts.tests_phase_i3
"""
from django.test import TestCase

from geofence.models import GeoFence
from devices.models import Device

from alerts.services.worker_evaluator import (
    _classify_state,
    _dynamic_zone_prefix,
    _build_message,
)


class DynamicZonePrefixTests(TestCase):
    """동적 zone prefix 생성 검증."""

    def setUp(self):
        self.device = Device.objects.create(
            device_id='i3_sensor', device_name='I3',
            sensor_type='gas', x=100, y=100,
        )

    def _make_dynamic_zone(self, tier='tentative', trigger='manual'):
        return GeoFence.objects.create(
            name='[동적] test',
            polygon=[[0, 0], [10, 0], [10, 10]],
            is_active=True,
            is_dynamic=True,
            source_device=self.device,
            gas_type='co',
            tier=tier,
            trigger_source=trigger,
            current_radius_px=50,
        )

    def test_static_zone_no_prefix(self):
        """정적 zone 은 prefix 없음."""
        static = GeoFence.objects.create(
            name='static', polygon=[[0,0],[10,0],[10,10]],
            is_dynamic=False, is_active=True,
        )
        self.assertEqual(_dynamic_zone_prefix(static), '')

    def test_critical_anomaly_prefix(self):
        """critical + ttm_anomaly → [긴급][실측]."""
        zone = self._make_dynamic_zone(tier='critical', trigger='ttm_anomaly')
        prefix = _dynamic_zone_prefix(zone)
        self.assertIn('[긴급]', prefix)
        self.assertIn('실측', prefix)

    def test_tentative_forecast_prefix(self):
        """tentative + ttm_forecast → [잠정][사전경고]."""
        zone = self._make_dynamic_zone(tier='tentative', trigger='ttm_forecast')
        prefix = _dynamic_zone_prefix(zone)
        self.assertIn('[잠정]', prefix)
        self.assertIn('사전경고', prefix)

    def test_unknown_trigger_only_tier(self):
        """unknown trigger 면 tier 만."""
        zone = self._make_dynamic_zone(tier='confirmed', trigger='unknown')
        prefix = _dynamic_zone_prefix(zone)
        self.assertEqual(prefix, '[확인] ')

    def test_none_geofence(self):
        """None geofence 안전 처리."""
        self.assertEqual(_dynamic_zone_prefix(None), '')


class ClassifyStateTests(TestCase):
    """_classify_state 의 동적 critical zone 처리."""

    def setUp(self):
        self.device = Device.objects.create(
            device_id='i3_cls_sensor', device_name='I3-cls',
            sensor_type='gas', x=200, y=200,
        )

    def test_dynamic_critical_triggers_critical_state(self):
        """동적 critical tier zone → 작업자 상태도 'critical'."""
        zone = GeoFence.objects.create(
            name='[동적-긴급]',
            polygon=[[0,0],[10,0],[10,10]],
            zone_type='danger',   # 동적 zone 은 항상 zone_type='danger' 로 생성
            is_active=True, is_dynamic=True,
            source_device=self.device,
            gas_type='co',
            tier='critical',
            trigger_source='ttm_anomaly',
        )
        state = _classify_state([zone], 'normal')
        self.assertEqual(state, 'critical')

    def test_dynamic_tentative_only_danger(self):
        """tentative tier 는 critical 까지 안 올라감 (zone_type=danger 기준)."""
        zone = GeoFence.objects.create(
            name='[동적-잠정]',
            polygon=[[0,0],[10,0],[10,10]],
            zone_type='danger', is_active=True, is_dynamic=True,
            source_device=self.device, gas_type='co',
            tier='tentative', trigger_source='manual',
        )
        state = _classify_state([zone], 'normal')
        self.assertEqual(state, 'danger')   # 'critical' 아님

    def test_restricted_still_works(self):
        """기존 동작: restricted 정적 zone 은 여전히 critical 트리거."""
        static = GeoFence.objects.create(
            name='restricted',
            polygon=[[0,0],[10,0],[10,10]],
            zone_type='restricted',
            is_active=True, is_dynamic=False,
        )
        state = _classify_state([static], 'normal')
        self.assertEqual(state, 'critical')


class BuildMessageTests(TestCase):
    """_build_message wrapper 검증."""

    def setUp(self):
        self.device = Device.objects.create(
            device_id='i3_msg_sensor', device_name='I3-msg',
            sensor_type='gas', x=300, y=300,
        )

    def test_dynamic_zone_prefix_in_message(self):
        """동적 zone 진입 메시지에 prefix 포함."""
        zone = GeoFence.objects.create(
            name='[동적] CO 확산',
            polygon=[[0,0],[10,0],[10,10]],
            zone_type='danger',
            is_active=True, is_dynamic=True,
            source_device=self.device, gas_type='co',
            tier='confirmed', trigger_source='ttm_anomaly',
        )
        msg = _build_message(
            'worker_01', 'safe', 'danger', zone, 'normal',
        )
        self.assertIn('[확인]', msg)
        self.assertIn('실측', msg)
        self.assertIn('worker_01', msg)

    def test_static_zone_unchanged(self):
        """정적 zone 메시지는 기존 동작 유지 (prefix 없음)."""
        static = GeoFence.objects.create(
            name='caution_zone',
            polygon=[[0,0],[10,0],[10,10]],
            zone_type='caution',
            is_active=True, is_dynamic=False,
        )
        msg = _build_message(
            'worker_02', 'safe', 'caution', static, 'normal',
        )
        # prefix 없음
        self.assertFalse(msg.startswith('['))
        self.assertIn('worker_02', msg)
