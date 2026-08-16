"""Tests du contrat commun des adaptateurs sociaux."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from api.integrations.default_publishers import register_default_publishers
from api.integrations.social import (
    PublisherNotRegisteredError,
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

    def test_missing_adapter_raises_not_registered_error(self):
        with self.assertRaises(PublisherNotRegisteredError) as raised:
            SocialPublisherRegistry().get(ChannelPlatform.TIKTOK)
        self.assertIn("pas encore configurée", str(raised.exception))
        self.assertIs(raised.exception.platform, ChannelPlatform.TIKTOK)

    def test_not_registered_is_distinct_from_provider_errors(self):
        # La configuration manquante ne doit pas se confondre avec une
        # erreur fournisseur (connexion/refus), gérées ailleurs en HTTP 4xx.
        self.assertNotIsInstance(
            PublisherNotRegisteredError(ChannelPlatform.INSTAGRAM), SocialPublisherError
        )
        with self.assertRaises(PublisherNotRegisteredError):
            SocialPublisherRegistry().get(ChannelPlatform.INSTAGRAM)

    def test_connect_route_maps_missing_adapter_to_503(self):
        from api.routes import social_integrations

        with patch.object(
            social_integrations, "social_publishers", SocialPublisherRegistry()
        ):
            with self.assertRaises(HTTPException) as raised:
                social_integrations._publisher(ChannelPlatform.FACEBOOK)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("pas encore configurée", raised.exception.detail)

    def test_default_publishers_fill_a_fresh_registry(self):
        registry = SocialPublisherRegistry()
        register_default_publishers(MagicMock(), registry)
        for platform in ChannelPlatform:
            self.assertTrue(
                registry.has(platform), f"{platform} devrait être enregistrée"
            )

    def test_default_publishers_registration_is_idempotent(self):
        registry = SocialPublisherRegistry()
        settings = MagicMock()
        register_default_publishers(settings, registry)
        # Un second appel (ex. worker après API) ne doit pas lever de doublon.
        register_default_publishers(settings, registry)
        self.assertTrue(registry.has(ChannelPlatform.YOUTUBE))
        self.assertTrue(registry.has(ChannelPlatform.INSTAGRAM))


if __name__ == "__main__":
    unittest.main()
