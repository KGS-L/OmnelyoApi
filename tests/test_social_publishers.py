"""Tests du contrat commun des adaptateurs sociaux."""
import unittest

from api.integrations.social import (
    SocialErrorCode,
    SocialPublisherError,
    SocialPublisherRegistry,
)
from api.models import ChannelPlatform


class FakePublisher:
    platform = ChannelPlatform.YOUTUBE


class SocialPublisherContractTests(unittest.TestCase):
    def test_all_requested_platforms_are_available(self):
        self.assertEqual(
            set(ChannelPlatform),
            {
                ChannelPlatform.YOUTUBE,
                ChannelPlatform.TIKTOK,
                ChannelPlatform.FACEBOOK,
                ChannelPlatform.INSTAGRAM,
            },
        )

    def test_registry_returns_registered_adapter(self):
        registry = SocialPublisherRegistry()
        publisher = FakePublisher()
        registry.register(publisher)
        self.assertIs(registry.get(ChannelPlatform.YOUTUBE), publisher)

    def test_duplicate_adapter_is_rejected(self):
        registry = SocialPublisherRegistry()
        registry.register(FakePublisher())
        with self.assertRaises(ValueError):
            registry.register(FakePublisher())

    def test_missing_adapter_has_normalized_error(self):
        with self.assertRaises(SocialPublisherError) as raised:
            SocialPublisherRegistry().get(ChannelPlatform.TIKTOK)
        self.assertEqual(raised.exception.code, SocialErrorCode.AUTHORIZATION)
        self.assertFalse(raised.exception.retryable)


if __name__ == "__main__":
    unittest.main()
