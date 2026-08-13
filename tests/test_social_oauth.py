"""Tests de sécurité du flux OAuth social générique."""
import unittest
import uuid

from api.integrations.social_oauth import SocialOAuthStateService
from api.models import ChannelPlatform
from api.schemas import SocialConnectionResponse


class FakeRedis:
    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = value

    def getdel(self, key):
        return self.values.pop(key, None)


class SocialOAuthStateTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.service = SocialOAuthStateService(self.redis, ttl_seconds=600)
        self.user_id = uuid.uuid4()
        self.workspace_id = uuid.uuid4()

    def test_state_is_single_use_and_bound_to_context(self):
        state = self.service.issue(
            self.user_id, self.workspace_id, ChannelPlatform.INSTAGRAM
        )
        pending = self.service.consume(state)
        self.assertEqual(pending.user_id, self.user_id)
        self.assertEqual(pending.workspace_id, self.workspace_id)
        self.assertIs(pending.platform, ChannelPlatform.INSTAGRAM)
        self.assertIsNone(self.service.consume(state))

    def test_raw_state_is_not_used_as_redis_key(self):
        state = self.service.issue(
            self.user_id, self.workspace_id, ChannelPlatform.YOUTUBE
        )
        self.assertTrue(all(state not in key for key in self.redis.values))

    def test_connection_response_cannot_expose_tokens(self):
        fields = SocialConnectionResponse.model_fields
        self.assertNotIn("access_token_encrypted", fields)
        self.assertNotIn("refresh_token_encrypted", fields)
        self.assertNotIn("provider_metadata", fields)


if __name__ == "__main__":
    unittest.main()
