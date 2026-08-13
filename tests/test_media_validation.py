"""Tests de la matrice de prévalidation des publications."""
import unittest
from datetime import datetime, timedelta, timezone

from api.integrations.media_validation import validate_publication_preflight
from api.integrations.social import SocialErrorCode, SocialPublisherError
from api.models import ChannelPlatform, PublicationVisibility


class MediaValidationTests(unittest.TestCase):
    def _validate(self, platform, **overrides):
        values = {
            "platform": platform,
            "storage_key": "workspaces/w/rendered/clip.mp4",
            "duration_seconds": 30,
            "title": "Titre",
            "description": "Description",
            "visibility": (
                PublicationVisibility.PRIVATE
                if platform is ChannelPlatform.TIKTOK
                else PublicationVisibility.PUBLIC
            ),
            "scheduled_at": None,
        }
        values.update(overrides)
        validate_publication_preflight(**values)

    def test_supported_platform_matrix_accepts_valid_media(self):
        for platform in ChannelPlatform:
            with self.subTest(platform=platform.value):
                self._validate(platform)

    def test_supported_platform_matrix_rejects_invalid_format(self):
        for platform in ChannelPlatform:
            with self.subTest(platform=platform.value):
                with self.assertRaises(SocialPublisherError) as raised:
                    self._validate(platform, storage_key="rendered/clip.avi")
                self.assertEqual(raised.exception.code, SocialErrorCode.VALIDATION)

    def test_unscheduled_platform_matrix_rejects_scheduling(self):
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        for platform in (
            ChannelPlatform.TIKTOK,
            ChannelPlatform.FACEBOOK,
            ChannelPlatform.INSTAGRAM,
        ):
            with self.subTest(platform=platform.value):
                with self.assertRaisesRegex(SocialPublisherError, "programmation"):
                    self._validate(platform, scheduled_at=scheduled_at)

    def test_platform_visibility_matrix_is_enforced(self):
        invalid_visibility = {
            ChannelPlatform.TIKTOK: PublicationVisibility.PUBLIC,
            ChannelPlatform.FACEBOOK: PublicationVisibility.PRIVATE,
            ChannelPlatform.INSTAGRAM: PublicationVisibility.PRIVATE,
        }
        for platform, visibility in invalid_visibility.items():
            with self.subTest(platform=platform.value):
                with self.assertRaises(SocialPublisherError) as raised:
                    self._validate(platform, visibility=visibility)
                self.assertEqual(raised.exception.code, SocialErrorCode.VALIDATION)

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

    def test_instagram_reel_is_accepted(self):
        validate_publication_preflight(
            platform=ChannelPlatform.INSTAGRAM,
            storage_key="rendered/clip.mp4",
            duration_seconds=60,
            title="Titre",
            description=None,
            visibility=PublicationVisibility.PUBLIC,
            scheduled_at=None,
        )

    def test_instagram_reel_duration_is_bounded(self):
        with self.assertRaisesRegex(SocialPublisherError, "15 minutes"):
            validate_publication_preflight(
                platform=ChannelPlatform.INSTAGRAM,
                storage_key="rendered/clip.mp4",
                duration_seconds=901,
                title="Titre",
                description=None,
                visibility=PublicationVisibility.PUBLIC,
                scheduled_at=None,
            )

    def test_facebook_reel_duration_is_bounded(self):
        with self.assertRaisesRegex(SocialPublisherError, "3 et 60"):
            validate_publication_preflight(
                platform=ChannelPlatform.FACEBOOK,
                storage_key="rendered/reel.mp4",
                duration_seconds=61,
                title="Reel",
                description=None,
                visibility=PublicationVisibility.PUBLIC,
                scheduled_at=None,
            )


if __name__ == "__main__":
    unittest.main()
