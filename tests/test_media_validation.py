"""Tests de la matrice de prévalidation des publications."""
import unittest
from datetime import datetime, timedelta, timezone

from api.integrations.media_validation import validate_publication_preflight
from api.integrations.social import SocialErrorCode, SocialPublisherError
from api.models import ChannelPlatform, PublicationVisibility


class MediaValidationTests(unittest.TestCase):
    def test_valid_youtube_short_is_accepted(self):
        validate_publication_preflight(
            platform=ChannelPlatform.YOUTUBE,
            storage_key="workspaces/w/rendered/clip.mp4",
            duration_seconds=180,
            title="Titre",
            description="Description",
            visibility=PublicationVisibility.PUBLIC,
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def test_youtube_short_over_three_minutes_is_rejected(self):
        with self.assertRaises(SocialPublisherError) as raised:
            validate_publication_preflight(
                platform=ChannelPlatform.YOUTUBE,
                storage_key="rendered/clip.mp4",
                duration_seconds=181,
                title="Titre",
                description=None,
                visibility=PublicationVisibility.PUBLIC,
                scheduled_at=None,
            )
        self.assertEqual(raised.exception.code, SocialErrorCode.VALIDATION)

    def test_scheduled_youtube_short_must_target_public_visibility(self):
        with self.assertRaisesRegex(SocialPublisherError, "visibilité publique"):
            validate_publication_preflight(
                platform=ChannelPlatform.YOUTUBE,
                storage_key="rendered/clip.mp4",
                duration_seconds=60,
                title="Titre",
                description=None,
                visibility=PublicationVisibility.PRIVATE,
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )

    def test_unavailable_platform_is_rejected_before_queue(self):
        with self.assertRaises(SocialPublisherError) as raised:
            validate_publication_preflight(
                platform=ChannelPlatform.INSTAGRAM,
                storage_key="rendered/clip.mp4",
                duration_seconds=60,
                title="Titre",
                description=None,
                visibility=PublicationVisibility.PUBLIC,
                scheduled_at=None,
            )
        self.assertEqual(raised.exception.code, SocialErrorCode.AUTHORIZATION)


if __name__ == "__main__":
    unittest.main()
