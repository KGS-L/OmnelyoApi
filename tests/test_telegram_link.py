"""Tests des jetons de liaison web vers Telegram."""
import unittest
import uuid

from api.integrations.telegram import TelegramLinkService


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl

    def getdel(self, key):
        self.ttls.pop(key, None)
        return self.values.pop(key, None)


class TelegramLinkServiceTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.service = TelegramLinkService(self.redis, ttl_seconds=600)
        self.user_id = uuid.uuid4()
        self.workspace_id = uuid.uuid4()

    def test_token_is_stored_hashed_with_ttl(self):
        token = self.service.issue(self.user_id, self.workspace_id)
        key = next(iter(self.redis.values))
        self.assertNotIn(token, key)
        self.assertEqual(self.redis.ttls[key], 600)

    def test_token_is_single_use(self):
        token = self.service.issue(self.user_id, self.workspace_id)
        pending = self.service.consume(token)
        self.assertEqual(pending.user_id, self.user_id)
        self.assertEqual(pending.workspace_id, self.workspace_id)
        self.assertIsNone(self.service.consume(token))

    def test_unknown_token_is_rejected(self):
        self.assertIsNone(self.service.consume("unknown"))


if __name__ == "__main__":
    unittest.main()
