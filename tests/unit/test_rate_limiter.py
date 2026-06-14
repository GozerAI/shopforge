"""Tests for RateLimiter."""

import time

from shopforge.shopify import RateLimiter


class TestRateLimiter:
    def test_initial_state(self):
        limiter = RateLimiter()
        assert limiter.bucket == 40
        assert limiter.bucket_max == 40
        assert limiter.calls_per_second == 2.0

    def test_wait_if_needed_updates_bucket_from_headers(self):
        limiter = RateLimiter()
        headers = {"X-Shopify-Shop-Api-Call-Limit": "35/40"}
        limiter.wait_if_needed(headers)

        assert limiter.bucket == 5  # 40 - 35
        assert limiter.bucket_max == 40

    def test_wait_if_needed_no_headers(self):
        limiter = RateLimiter()
        # Should not raise
        limiter.wait_if_needed(None)
        assert limiter.last_call > 0

    def test_custom_calls_per_second(self):
        limiter = RateLimiter(calls_per_second=4.0)
        assert limiter.calls_per_second == 4.0
