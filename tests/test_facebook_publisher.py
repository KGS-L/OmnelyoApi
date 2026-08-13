"""Tests de l'adaptateur Facebook Pages/Reels."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from api.integrations.facebook import FacebookPublisher
from api.integrations.social import PublishRequest, SocialPublisherError
from api.integrations.social import PublisherCredentials
from api.models import PublicationVisibility


class FacebookPublisherTests(unittest.TestCase):
    def setUp(self):
        self.publisher = FacebookPublisher("app", "secret", "v23.0")

    def test_oauth_url_requests_page_permissions(self):
        url = self.publisher.connect("state-safe", "https://api.test/callback")
        self.assertIn("pages_manage_posts", url)
        self.assertIn("state-safe", url)

    @patch.object(FacebookPublisher, "_request")
    def test_oauth_returns_one_grant_per_page_token(self, request):
        request.side_effect = [
            {"access_token": "user-token"},
            {"data": [
                {"id": "page-a", "name": "A", "access_token": "token-a"},
                {"id": "page-b", "name": "B", "access_token": "token-b"},
            ]},
        ]
        grants = self.publisher.exchange_code("code", "https://api.test/callback")
        self.assertEqual([grant.provider_account_id for grant in grants], ["page-a", "page-b"])
        self.assertEqual(grants[1].access_token, "token-b")

    def test_reel_requires_public_visibility(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            request = PublishRequest(
                Path(video.name), "Titre", None, PublicationVisibility.PRIVATE
            )
            with self.assertRaisesRegex(SocialPublisherError, "publique"):
                self.publisher.validate_media(request)

    @patch("api.integrations.facebook.requests.post")
    @patch.object(FacebookPublisher, "_request")
    def test_publish_starts_upload_and_finishes_reel(self, graph_request, upload):
        graph_request.side_effect = [
            {"video_id": "video-1", "upload_url": "https://upload.test/reel"},
            {"success": True},
        ]
        upload.return_value = Mock(status_code=200)
        upload.return_value.raise_for_status.return_value = None
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            result = self.publisher.publish(
                PublisherCredentials("page-token", None, [], None),
                "page-1",
                PublishRequest(
                    Path(video.name), "Titre", "Description", PublicationVisibility.PUBLIC
                ),
            )
        self.assertEqual(result.external_id, "video-1")
        self.assertEqual(result.status, "processing")
        self.assertEqual(graph_request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
