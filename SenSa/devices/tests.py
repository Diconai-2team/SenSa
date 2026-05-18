"""
devices 테스트 — 근접도 메모리 캐시

usage:
    python manage.py test devices
"""
from django.test import TestCase

from devices.models import Device
from devices.neighbor_graph import (
    get_distance,
    get_neighbors_within,
    invalidate_neighbor_cache,
    cache_stats,
)


class NeighborGraphTests(TestCase):
    """근접도 메모리 캐시 검증."""

    def setUp(self):
        invalidate_neighbor_cache()
        self.d1 = Device.objects.create(
            device_id='test_n1', device_name='Test N1',
            sensor_type='gas', x=0, y=0,
        )
        self.d2 = Device.objects.create(
            device_id='test_n2', device_name='Test N2',
            sensor_type='gas', x=30, y=40,  # 거리 50 (3-4-5)
        )
        self.d3 = Device.objects.create(
            device_id='test_n3', device_name='Test N3',
            sensor_type='gas', x=100, y=0,  # d1과 거리 100
        )

    def tearDown(self):
        invalidate_neighbor_cache()

    def test_distance_calculation(self):
        """거리 계산 정확성 (3-4-5 직각삼각형)."""
        d = get_distance(self.d1.id, self.d2.id)
        self.assertAlmostEqual(d, 50.0, places=1)

    def test_distance_to_self_is_none(self):
        """자기 자신과의 거리는 캐시에 없음 (None)."""
        self.assertIsNone(get_distance(self.d1.id, self.d1.id))

    def test_neighbors_within_radius(self):
        """반경 내 이웃만 반환."""
        within = get_neighbors_within(self.d1.id, 60.0)
        self.assertEqual(len(within), 1)
        self.assertEqual(within[0][0], self.d2.id)

    def test_neighbors_sorted_by_distance(self):
        """결과는 거리 오름차순."""
        within = get_neighbors_within(self.d1.id, 150.0)
        self.assertEqual(len(within), 2)
        self.assertEqual(within[0][0], self.d2.id)   # 50px
        self.assertEqual(within[1][0], self.d3.id)   # 100px

    def test_invalidate_resets_cache(self):
        """invalidate 후 재로드 정상 동작."""
        get_neighbors_within(self.d1.id, 1000)
        self.assertTrue(cache_stats()['loaded'])

        invalidate_neighbor_cache()
        # 다음 호출에서 자동 재로드
        d = get_distance(self.d1.id, self.d2.id)
        self.assertAlmostEqual(d, 50.0, places=1)

    def test_power_sensor_excluded_from_gas_graph(self):
        """전력 센서는 가스 그래프에 포함되지 않음."""
        Device.objects.create(
            device_id='test_power_n', device_name='Power N',
            sensor_type='power', x=10, y=10,
        )
        invalidate_neighbor_cache()

        within = get_neighbors_within(self.d1.id, 1000)
        target_ids = [tid for tid, _ in within]
        self.assertEqual(len(target_ids), 2)   # d2, d3 만 (전력 제외)
