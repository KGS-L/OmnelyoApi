"""Tests de l'adaptateur TikTok sandbox."""
import tempfile
import unittest
from pathlib import Path

from api.integrations.social import PublishRequest, SocialPublisherError
from api.integrations.tiktok import TikTokPublisher
from api.models import PublicationVisibility


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


if __name__ == "__main__":
    unittest.main()
