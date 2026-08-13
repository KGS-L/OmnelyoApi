"""Tests unitaires de l'adaptateur social YouTube."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api.integrations.social import (
    PublisherCredentials,
    PublishRequest,
    SocialErrorCode,
    SocialPublisherError,
)
from api.integrations.youtube import YouTubePublisher, _youtube_error
from api.models import PublicationVisibility


class YouTubePublisherTests(unittest.TestCase):
    def setUp(self):
        self.publisher = YouTubePublisher(Path("client-secret.json"))
        self.credentials = PublisherCredentials(
            access_token="access",
            refresh_token="refresh",
            scopes=["youtube"],
            expires_at=None,
        )

    def test_channel_response_is_normalized(self):
        execute = Mock(
            return_value={
                "items": [
                    {
                        "id": "channel-1",
                        "snippet": {
                            "title": "ShortPilot",
                            "customUrl": "@shortpilot",
                            "thumbnails": {"high": {"url": "https://img.test/a.jpg"}},
                        },
                    }
                ]
            }
        )
        service = Mock()
        service.channels.return_value.list.return_value.execute = execute
        with patch.object(self.publisher, "_service", return_value=service):
            channels = self.publisher.list_channels(self.credentials)
        self.assertEqual(channels[0].external_id, "channel-1")
        self.assertEqual(channels[0].handle, "@shortpilot")

    def test_scheduled_upload_requires_public_visibility(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            request = PublishRequest(
                media_path=Path(video.name),
                title="Titre",
                description=None,
                visibility=PublicationVisibility.PRIVATE,
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            with self.assertRaises(SocialPublisherError) as raised:
                self.publisher.validate_media(request)
        self.assertEqual(raised.exception.code, SocialErrorCode.VALIDATION)

    def test_missing_media_is_rejected(self):
        request = PublishRequest(
            media_path=Path("/tmp/shortpilot-missing-video.mp4"),
            title="Titre",
            description=None,
            visibility=PublicationVisibility.PUBLIC,
        )
        with self.assertRaises(SocialPublisherError) as raised:
            self.publisher.validate_media(request)
        self.assertEqual(raised.exception.code, SocialErrorCode.VALIDATION)

    def test_server_error_is_retryable(self):
        error = _youtube_error(SimpleNamespace(resp=SimpleNamespace(status=503)))
        self.assertEqual(error.code, SocialErrorCode.TEMPORARY)
        self.assertTrue(error.retryable)


if __name__ == "__main__":
    unittest.main()
