"""认证接口限流测试。"""
from __future__ import annotations
import unittest
from unittest.mock import patch

from config import settings
from core.rate_limit import hit_auth_limit


class RateLimitUnitTests(unittest.TestCase):
    def test_limit_blocks_after_threshold(self):
        with patch.object(settings, "auth_rate_limit_per_minute", 3):
            self.assertTrue(hit_auth_limit("k1"))
            self.assertTrue(hit_auth_limit("k1"))
            self.assertTrue(hit_auth_limit("k1"))
            self.assertFalse(hit_auth_limit("k1"))
            # 不同键互不影响
            self.assertTrue(hit_auth_limit("k2"))

    def test_disabled_limit_allows_all(self):
        with patch.object(settings, "auth_rate_limit_per_minute", 0):
            for _ in range(200):
                self.assertTrue(hit_auth_limit("k3"))


if __name__ == "__main__":
    unittest.main()
