"""Tests de l'adaptateur TikTok sandbox."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.integrations.social import PublisherCredentials, PublishRequest, SocialPublisherError
from api.integrations.tiktok import TikTokPublisher
from api.models import PublicationFormat, PublicationVisibility


class TikTokPublisherTests(unittest.TestCase):
    def test_authorization_url_contains_state_and_scopes(self):
        url = TikTokPublisher("key", "secret").connect("safe-state", "https://api.test/callback")
        self.assertIn("safe-state", url)
        self.assertIn("video.publish", url)

    def test_sandbox_rejects_public_visibility(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            request = PublishRequest(
                Path(video.name), "Titre", None, PublicationVisibility.PUBLIC
            )
            with self.assertRaisesRegex(SocialPublisherError, "SELF_ONLY"):
                TikTokPublisher("key", "secret").validate_media(request)

    def test_sandbox_accepts_private_mp4(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            request = PublishRequest(
                Path(video.name), "Titre", None, PublicationVisibility.PRIVATE
            )
            TikTokPublisher("key", "secret").validate_media(request)

    @patch.object(TikTokPublisher, "_request")
    def test_photo_uses_content_init_with_pull_urls(self, request):
        request.return_value = {"data": {"publish_id": "photo-1"}}
        with tempfile.NamedTemporaryFile(suffix=".jpg") as first, tempfile.NamedTemporaryFile(suffix=".png") as second:
            result = TikTokPublisher("key", "secret").publish(
                PublisherCredentials("token", None, [], None),
                "account",
                PublishRequest(
                    Path(first.name), "Titre", "Légende", PublicationVisibility.PRIVATE,
                    format=PublicationFormat.CAROUSEL,
                    media_paths=(Path(first.name), Path(second.name)),
                    media_urls=("https://cdn.test/1.jpg", "https://cdn.test/2.png"),
                ),
            )
        self.assertEqual(result.external_id, "photo-1")
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["media_type"], "PHOTO")
        self.assertEqual(payload["source_info"]["photo_images"], ["https://cdn.test/1.jpg", "https://cdn.test/2.png"])


if __name__ == "__main__":
    unittest.main()
