"""Tests du registre et du signal de réveil des workers."""
import unittest

from redis.exceptions import ConnectionError

from api.models import JobType
from workers.registry import HandlerRegistry
from workers.signals import notify_workers


def fake_handler(job, heartbeat):
    return {"ok": True}


class FakeRedis:
    def __init__(self, fail=False):
        self.fail = fail
        self.messages = []

    def publish(self, channel, message):
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.messages.append((channel, message))
        return 1


class HandlerRegistryTests(unittest.TestCase):
    def test_only_registered_types_are_exposed(self):
        registry = HandlerRegistry()
        registry.register(JobType.INGEST, fake_handler)
        self.assertEqual(registry.job_types, frozenset({JobType.INGEST}))
        self.assertIs(registry.get(JobType.INGEST), fake_handler)
        self.assertIsNone(registry.get(JobType.RENDER))

    def test_duplicate_handler_is_rejected(self):
        registry = HandlerRegistry()
        registry.register(JobType.INGEST, fake_handler)
        with self.assertRaises(ValueError):
            registry.register(JobType.INGEST, fake_handler)


class WorkerSignalTests(unittest.TestCase):
    def test_notification_is_published(self):
        redis = FakeRedis()
        self.assertTrue(notify_workers(redis, "job-1"))
        self.assertEqual(redis.messages[0][1], "job-1")

    def test_redis_failure_falls_back_to_polling(self):
        with self.assertLogs("workers.signals", level="WARNING") as logs:
            self.assertFalse(notify_workers(FakeRedis(fail=True), "job-1"))
        self.assertIn("polling PostgreSQL", logs.output[0])


if __name__ == "__main__":
    unittest.main()
