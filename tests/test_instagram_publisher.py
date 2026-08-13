"""Tests de l'adaptateur Instagram professionnel."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.integrations.instagram import InstagramPublisher
from api.integrations.social import PublisherCredentials, PublishRequest, SocialPublisherError
from api.models import PublicationVisibility


class InstagramPublisherTests(unittest.TestCase):
    def setUp(self):
        self.publisher = InstagramPublisher("app", "secret", "v23.0")

    @patch.object(InstagramPublisher, "_request")
    def test_oauth_discovers_only_pages_with_professional_account(self, request):
        request.side_effect = [
            {"access_token": "user-token"},
            {"data": [
                {"id": "page-empty", "name": "Sans Instagram", "access_token": "p0"},
                {"id": "page-1", "name": "Page", "access_token": "page-token",
                 "instagram_business_account": {"id": "ig-1", "username": "shortpilot"}},
            ]},
        ]
        grants = self.publisher.exchange_code("code", "https://api.test/callback")
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].provider_account_id, "ig-1")
        self.assertEqual(grants[0].access_token, "page-token")
        self.assertEqual(grants[0].provider_metadata["facebook_page_id"], "page-1")

    def test_reel_requires_https_media_url(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            with self.assertRaisesRegex(SocialPublisherError, "URL HTTPS"):
                self.publisher.validate_media(PublishRequest(
                    Path(video.name), "Titre", None, PublicationVisibility.PUBLIC
                ))

    @patch("api.integrations.instagram.time.sleep")
    @patch.object(InstagramPublisher, "_request")
    def test_reel_container_is_published_after_processing(self, request, sleep):
        request.side_effect = [
            {"id": "container-1"},
            {"status_code": "IN_PROGRESS"},
            {"status_code": "FINISHED"},
            {"id": "media-1"},
        ]
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            result = self.publisher.publish(
                PublisherCredentials("page-token", None, [], None),
                "ig-1",
                PublishRequest(
                    Path(video.name), "Titre", "Légende", PublicationVisibility.PUBLIC,
                    media_url="https://signed.example/reel.mp4?sig=x",
                ),
            )
        self.assertEqual(result.external_id, "media-1")
        self.assertEqual(result.raw_response["container_id"], "container-1")
        sleep.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()
