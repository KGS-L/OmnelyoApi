"""Tests du contrat du handler PUBLISH."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.integrations.social import PublisherCredentials
from api.models import JobType, PublicationStatus
from workers.handlers.publish import (
    FAILED_PROVIDER_STATUSES,
    PUBLISHED_PROVIDER_STATUSES,
    _needs_refresh,
    _persist_reconciliation,
    _result,
    _tiktok_media_urls,
)
from workers.registry import JobDeferred, registry


class PublishHandlerTests(unittest.TestCase):
    def test_tiktok_urls_use_verified_public_domain(self):
        self.assertEqual(
            _tiktok_media_urls(("workspaces/w/media-assets/a/source.jpg",), "https://media.test/"),
            ("https://media.test/workspaces/w/media-assets/a/source.jpg",),
        )

    def test_tiktok_urls_reject_missing_verified_domain(self):
        with self.assertRaisesRegex(ValueError, "TIKTOK_VERIFIED_MEDIA_BASE_URL"):
            _tiktok_media_urls(("image.jpg",), "")

    def test_publish_handler_is_registered(self):
        self.assertIsNotNone(registry.get(JobType.PUBLISH))

    def test_credentials_near_expiry_require_refresh(self):
        credentials = PublisherCredentials(
            access_token="access",
            refresh_token="refresh",
            scopes=[],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
        )
        self.assertTrue(_needs_refresh(credentials))

    def test_credentials_without_expiry_do_not_require_refresh(self):
        credentials = PublisherCredentials("access", None, [], None)
        self.assertFalse(_needs_refresh(credentials))

    def test_result_contains_stable_identifiers(self):
        publication_id = uuid.uuid4()
        self.assertEqual(
            _result(publication_id, "youtube-id"),
            {"publication_id": str(publication_id), "external_id": "youtube-id"},
        )

    def test_provider_statuses_have_distinct_terminal_groups(self):
        self.assertIn("publish_complete", PUBLISHED_PROVIDER_STATUSES)
        self.assertIn("ready", PUBLISHED_PROVIDER_STATUSES)
        self.assertIn("failed", FAILED_PROVIDER_STATUSES)
        self.assertTrue(PUBLISHED_PROVIDER_STATUSES.isdisjoint(FAILED_PROVIDER_STATUSES))

    def test_deferred_job_exposes_polling_delay(self):
        deferred = JobDeferred("Traitement en cours", delay_seconds=45)
        self.assertEqual(deferred.delay_seconds, 45)
        self.assertEqual(str(deferred), "Traitement en cours")

    def test_reconciliation_marks_completed_provider_publication(self):
        publication = SimpleNamespace(
            provider_response=None,
            status=PublicationStatus.PUBLISHING,
            published_at=None,
            error_message="ancienne erreur",
        )
        db = MagicMock()
        db.get.return_value = publication
        session = MagicMock()
        session.__enter__.return_value = db
        context = SimpleNamespace(
            publication_id=uuid.uuid4(), external_id=None,
            existing_external_id="provider-id",
        )
        with patch("workers.handlers.publish.SessionLocal", return_value=session):
            result = _persist_reconciliation(context, "PUBLISH_COMPLETE")
        self.assertEqual(publication.status, PublicationStatus.PUBLISHED)
        self.assertIsNotNone(publication.published_at)
        self.assertEqual(result["external_id"], "provider-id")
        db.commit.assert_called_once()

    def test_reconciliation_defers_non_terminal_provider_status(self):
        publication = SimpleNamespace(
            provider_response={},
            status=PublicationStatus.PUBLISHING,
            published_at=None,
            error_message=None,
        )
        db = MagicMock()
        db.get.return_value = publication
        session = MagicMock()
        session.__enter__.return_value = db
        context = SimpleNamespace(
            publication_id=uuid.uuid4(), existing_external_id="provider-id",
        )
        with patch("workers.handlers.publish.SessionLocal", return_value=session):
            with self.assertRaises(JobDeferred):
                _persist_reconciliation(context, "PROCESSING_UPLOAD")
        self.assertEqual(publication.status, PublicationStatus.PUBLISHING)
        self.assertEqual(
            publication.provider_response["reconciled_status"], "PROCESSING_UPLOAD"
        )


if __name__ == "__main__":
    unittest.main()
