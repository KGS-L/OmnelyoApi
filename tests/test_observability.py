"""Tests du socle de corrélation et de limitation des requêtes."""
import json
import logging
import unittest

from api.observability import JSONFormatter, RateLimitMiddleware, request_id_context


class FakePipeline:
    def __init__(self, count):
        self.count = count

    def incr(self, key):
        return self

    def expire(self, key, ttl):
        return self

    def execute(self):
        return self.count, True


class FakeRedis:
    def __init__(self, count):
        self.count = count

    def pipeline(self):
        return FakePipeline(self.count)


class ObservabilityTests(unittest.TestCase):
    def test_json_logs_include_request_id(self):
        token = request_id_context.set("request-123")
        try:
            record = logging.LogRecord("api", logging.INFO, __file__, 1, "ok", (), None)
            payload = json.loads(JSONFormatter().format(record))
        finally:
            request_id_context.reset(token)
        self.assertEqual(payload["request_id"], "request-123")
        self.assertEqual(payload["message"], "ok")

    def test_rate_limit_reports_remaining_capacity(self):
        middleware = RateLimitMiddleware(lambda scope: None, "redis://localhost", 3)
        middleware.redis = FakeRedis(2)
        self.assertEqual(middleware._consume("key"), (True, 1))
        middleware.redis = FakeRedis(4)
        self.assertEqual(middleware._consume("key"), (False, 0))


if __name__ == "__main__":
    unittest.main()
