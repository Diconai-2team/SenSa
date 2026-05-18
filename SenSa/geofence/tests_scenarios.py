"""
geofence/tests_scenarios.py — Phase D 시나리오 회귀 테스트.

각 시나리오의 execute(verify=True) 가 통과하는지 자동 검증.
시나리오 자체가 setup → run → expected → teardown 을 캡슐화하므로
TestCase 는 호출만 하고 결과 dict 만 확인.

[critical 시나리오 mock]
    MultiLeak / SuddenLeak 는 'upgraded_to_critical' 이벤트를 발행하며,
    events.py 의 `_notify_external_critical` 이 Celery task 를 큐잉.
    운영 worker 동시 동작 시 실제 Slack/Discord 발송 위험.
    회귀 테스트는 `send_external_notification_task.delay` 를 mock 으로 가림.
"""
from unittest.mock import patch

from django.test import TestCase

from geofence.scenarios import (
    SCENARIO_REGISTRY, get_scenario, list_scenarios,
)


# ─────────────────────────────────────────────────────────────
# 레지스트리 + 기본 동작
# ─────────────────────────────────────────────────────────────

class ScenarioRegistryTests(TestCase):
    """레지스트리 기본 동작."""

    def test_registry_not_empty(self):
        self.assertGreater(len(SCENARIO_REGISTRY), 0)

    def test_registry_has_all_phase_d_scenarios(self):
        """Phase D-1, D-2 시나리오 모두 등록됨."""
        for name in ('single_leak', 'multi_leak', 'sudden_leak'):
            self.assertIn(
                name, SCENARIO_REGISTRY,
                msg=f"'{name}' 미등록 — D-1/D-2 시나리오 누락",
            )

    def test_get_scenario_unknown_raises(self):
        with self.assertRaises(KeyError):
            get_scenario('nonexistent_scenario_xyz')

    def test_list_scenarios_shape(self):
        items = list_scenarios()
        self.assertGreater(len(items), 0)
        for item in items:
            self.assertIn('name', item)
            self.assertIn('description', item)


# ─────────────────────────────────────────────────────────────
# Phase D-1 — SingleLeak (confirmed 승격)
# ─────────────────────────────────────────────────────────────

class SingleLeakScenarioTests(TestCase):
    """SingleLeak 회귀 검증 — Phase D-1 핵심 테스트."""

    def test_single_leak_verifies(self):
        """SingleLeak 시나리오가 기대 결과대로 동작."""
        cls = get_scenario('single_leak')
        scenario = cls()
        result = scenario.execute(verify=True, keep=False)

        self.assertEqual(result['status'], 'success',
                         msg=f"실행 실패: {result.get('error')}")
        self.assertTrue(
            result.get('verify_ok'),
            msg=f"검증 실패. diffs={result.get('verify_diffs')}",
        )
        self.assertTrue(result['cleaned_up'])

    def test_single_leak_actual_shape(self):
        """결과 dict 가 기대 필드를 모두 갖춤."""
        cls = get_scenario('single_leak')
        scenario = cls()
        result = scenario.execute(verify=False, keep=False)

        actual = result['actual']
        self.assertEqual(actual['zones_created'], 1)
        self.assertEqual(actual['critical_count'], 0)
        self.assertEqual(actual['confirmed_count'], 1)
        self.assertIn('created', actual['event_types'])
        self.assertIn('upgraded_to_confirmed', actual['event_types'])

    def test_single_leak_cleanup_after_keep_false(self):
        """keep=False 시 zone + device 가 모두 정리됨."""
        from geofence.models import GeoFence
        from devices.models import Device

        cls = get_scenario('single_leak')
        scenario = cls()
        result = scenario.execute(verify=False, keep=False)

        zone_ids = scenario.created_zone_ids
        device_ids = scenario.created_device_ids

        self.assertGreater(len(zone_ids), 0)
        self.assertGreater(len(device_ids), 0)

        self.assertEqual(
            GeoFence.objects.filter(id__in=zone_ids).count(), 0,
        )
        self.assertEqual(
            Device.objects.filter(id__in=device_ids).count(), 0,
        )

    def test_single_leak_keep_preserves(self):
        """keep=True 시 zone 이 DB 에 남음. 수동 cleanup."""
        from geofence.models import GeoFence

        cls = get_scenario('single_leak')
        scenario = cls()
        result = scenario.execute(verify=False, keep=True)

        try:
            self.assertFalse(result['cleaned_up'])
            self.assertEqual(
                GeoFence.objects.filter(
                    id__in=result['kept_zone_ids']
                ).count(),
                1,
            )
        finally:
            scenario.teardown()
            self.assertEqual(
                GeoFence.objects.filter(
                    id__in=result['kept_zone_ids']
                ).count(),
                0,
            )


# ─────────────────────────────────────────────────────────────
# Phase D-2 — Critical 시나리오 (외부 알림 mock)
# ─────────────────────────────────────────────────────────────

class CriticalScenarioMixin:
    """critical 시나리오 공통 setUp/tearDown — 외부 알림 task 호출 mock.

    Celery worker 가 운영 중일 때 회귀 테스트 도중 실제 Slack/Discord
    발송이 일어나는 것을 방지.
    """

    def setUp(self):
        super().setUp()
        self._patcher = patch(
            'alerts.tasks.send_external_notification_task.delay'
        )
        self.mock_notify_task = self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        super().tearDown()


class MultiLeakScenarioTests(CriticalScenarioMixin, TestCase):
    """MultiLeak 회귀 — 이웃 3개 → critical 승격."""

    def test_multi_leak_verifies(self):
        cls = get_scenario('multi_leak')
        scenario = cls()
        result = scenario.execute(verify=True, keep=False)

        self.assertEqual(result['status'], 'success',
                         msg=f"실행 실패: {result.get('error')}")
        self.assertTrue(
            result.get('verify_ok'),
            msg=f"검증 실패. diffs={result.get('verify_diffs')}",
        )

    def test_multi_leak_critical_direct_jump(self):
        """tentative → critical 직점프 (confirmed 이벤트 발행 X)."""
        cls = get_scenario('multi_leak')
        scenario = cls()
        result = scenario.execute(verify=False, keep=False)

        actual = result['actual']
        self.assertEqual(actual['critical_count'], 1)
        self.assertEqual(actual['confirmed_count'], 0)
        # confirmed 이벤트가 발행되지 않아야 함 (critical 직점프)
        self.assertNotIn(
            'upgraded_to_confirmed', actual['event_types'],
            msg=f"이웃 3개 한 tick 처리 시 confirmed 거치지 않고 "
                f"critical 직점프해야 함. event_types={actual['event_types']}",
        )
        self.assertIn('upgraded_to_critical', actual['event_types'])

    def test_multi_leak_triggers_external_notify(self):
        """critical 승격 시 외부 알림 task 가 큐잉됨."""
        cls = get_scenario('multi_leak')
        scenario = cls()
        scenario.execute(verify=False, keep=False)

        # is_configured() 가 True 면 task.delay 호출됨
        from alerts.notifiers import is_configured
        if is_configured():
            self.assertGreaterEqual(
                self.mock_notify_task.call_count, 1,
                msg='critical 승격 후 send_external_notification_task.delay '
                    '호출 기대',
            )


class SuddenLeakScenarioTests(CriticalScenarioMixin, TestCase):
    """SuddenLeak 회귀 — H2S 가스 (다른 임계) 검증."""

    def test_sudden_leak_verifies(self):
        cls = get_scenario('sudden_leak')
        scenario = cls()
        result = scenario.execute(verify=True, keep=False)

        self.assertEqual(result['status'], 'success',
                         msg=f"실행 실패: {result.get('error')}")
        self.assertTrue(
            result.get('verify_ok'),
            msg=f"검증 실패. diffs={result.get('verify_diffs')}",
        )

    def test_sudden_leak_uses_h2s_gas(self):
        """zone 의 gas_type 이 h2s 인지 + critical 도달 확인."""
        from geofence.models import GeoFence

        cls = get_scenario('sudden_leak')
        scenario = cls()
        result = scenario.execute(verify=False, keep=True)

        try:
            zone = GeoFence.objects.get(id=result['kept_zone_ids'][0])
            self.assertEqual(zone.gas_type, 'h2s')
            self.assertEqual(zone.tier, 'critical')
        finally:
            scenario.teardown()
