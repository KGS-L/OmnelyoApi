"""Validation des planifications et transitions de publications."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError

from api.models import PublicationStatus
from api.routes.publications import cancel_publication_record, update_publication_record
from api.schemas import (
    PublicationBatchCreate,
    PublicationBatchPublish,
    PublicationCreate,
    PublicationDestinationCreate,
    PublicationUpdate,
)


class PublicationSchemaTests(unittest.TestCase):
    def test_naive_schedule_is_rejected(self):
        with self.assertRaises(ValidationError):
            PublicationCreate(
                video_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                title="Publication",
                scheduled_at=datetime.now(),
            )

    def test_aware_schedule_is_accepted(self):
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        payload = PublicationCreate(
            video_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            title="Publication",
            scheduled_at=scheduled_at,
        )
        self.assertEqual(payload.scheduled_at, scheduled_at)

    def test_batch_rejects_duplicate_destination(self):
        channel_id = uuid.uuid4()
        with self.assertRaises(ValueError):
            PublicationBatchCreate(
                video_id=uuid.uuid4(),
                destinations=[
                    PublicationDestinationCreate(channel_id=channel_id, title="YouTube"),
                    PublicationDestinationCreate(channel_id=channel_id, title="Doublon"),
                ],
            )

    def test_batch_publish_rejects_duplicate_publication(self):
        publication_id = uuid.uuid4()
        with self.assertRaises(ValueError):
            PublicationBatchPublish(
                publication_ids=[publication_id, publication_id]
            )


class PublicationTransitionTests(unittest.TestCase):
    def test_draft_can_be_scheduled(self):
        publication = SimpleNamespace(status=PublicationStatus.DRAFT)
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
        update_publication_record(
            publication, PublicationUpdate(scheduled_at=scheduled_at)
        )
        self.assertEqual(publication.status, PublicationStatus.SCHEDULED)
        self.assertEqual(publication.scheduled_at, scheduled_at)

    def test_published_item_cannot_be_edited(self):
        publication = SimpleNamespace(status=PublicationStatus.PUBLISHED)
        with self.assertRaises(HTTPException) as caught:
            update_publication_record(
                publication, PublicationUpdate(title="Nouveau titre")
            )
        self.assertEqual(caught.exception.status_code, 409)

    def test_scheduled_item_can_be_cancelled(self):
        publication = SimpleNamespace(status=PublicationStatus.SCHEDULED)
        cancel_publication_record(publication)
        self.assertEqual(publication.status, PublicationStatus.CANCELLED)

    def test_published_item_cannot_be_cancelled(self):
        publication = SimpleNamespace(status=PublicationStatus.PUBLISHED)
        with self.assertRaises(HTTPException) as caught:
            cancel_publication_record(publication)
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
