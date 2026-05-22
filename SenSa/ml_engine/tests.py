"""
ml_engine/tests.py — ml_engine 모듈 단위 테스트.

usage:
    python manage.py test ml_engine
"""
from unittest.mock import patch, MagicMock
from django.test import TestCase

import redis


class SlidingWindowRedisErrorTests(TestCase):
    """sliding_window: Redis 오류 시 안전 fallback 검증."""

    def _raise_redis_error(self, *args, **kwargs):
        raise redis.ConnectionError("Redis 연결 실패 (테스트)")

    @patch("ml_engine.sliding_window._client")
    def test_push_silently_ignores_redis_error(self, mock_client):
        """push() 는 Redis 오류 시 예외를 전파하지 않는다."""
        mock_client.return_value.pipeline.side_effect = self._raise_redis_error
        from ml_engine.sliding_window import push
        # 예외 없이 반환되어야 함
        push("dev_01", "co", 15.0)

    @patch("ml_engine.sliding_window._client")
    def test_get_values_returns_empty_on_redis_error(self, mock_client):
        """get_values() 는 Redis 오류 시 빈 리스트를 반환한다."""
        mock_client.return_value.zrange.side_effect = self._raise_redis_error
        from ml_engine.sliding_window import get_values
        result = get_values("dev_01", "co")
        self.assertEqual(result, [])

    @patch("ml_engine.sliding_window._client")
    def test_size_returns_zero_on_redis_error(self, mock_client):
        """size() 는 Redis 오류 시 0을 반환한다."""
        mock_client.return_value.zcard.side_effect = self._raise_redis_error
        from ml_engine.sliding_window import size
        result = size("dev_01", "co")
        self.assertEqual(result, 0)

    @patch("ml_engine.sliding_window._client")
    def test_get_values_parses_members_correctly(self, mock_client):
        """get_values() 는 'ts:value' 형식을 올바르게 파싱한다."""
        mock_r = MagicMock()
        mock_client.return_value = mock_r
        mock_r.zrange.return_value = ["1700000000.0:10.5", "1700000001.0:20.3", "bad_member"]
        from ml_engine.sliding_window import get_values
        result = get_values("dev_01", "co")
        self.assertEqual(result, [10.5, 20.3])  # bad_member 무시됨
