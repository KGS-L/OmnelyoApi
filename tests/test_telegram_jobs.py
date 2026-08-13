"""Tests du passage du bot Telegram au pipeline PostgreSQL."""
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.integrations.telegram_jobs import (
    cancel_job_from_telegram,
    enqueue_url_from_telegram,
    import_video_from_telegram,
)
from api.models import JobStatus, JobType, VideoStatus


class TelegramJobTests(unittest.TestCase):
    def setUp(self):
        self.workspace_id = uuid.uuid4()
        self.connection = SimpleNamespace(workspace_id=self.workspace_id)

    def test_url_creates_ingest_job_in_linked_workspace(self):
        db = MagicMock()
        db.scalar.return_value = self.connection

        def assign_video_id():
            video = db.add.call_args_list[0].args[0]
            video.id = uuid.uuid4()

        db.flush.side_effect = assign_video_id
        job = enqueue_url_from_telegram(db, 123, "https://example.com/video")
        self.assertEqual(job.workspace_id, self.workspace_id)
        self.assertEqual(job.type, JobType.INGEST)
        self.assertEqual(job.payload["source"], "telegram")
        db.commit.assert_called_once()

    @patch("core.storage_r2.upload_to_r2")
    def test_uploaded_short_becomes_ready_workspace_video(self, upload):
        db = MagicMock()
        db.scalar.return_value = self.connection
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "telegram.part"
            source.write_bytes(b"video")
            video = import_video_from_telegram(
                db, 123, source, "video/mp4", 42.0, "Mon short"
            )
        self.assertEqual(video.workspace_id, self.workspace_id)
        self.assertEqual(video.status, VideoStatus.READY)
        self.assertEqual(video.storage_key, video.rendered_storage_key)
        self.assertIn(f"workspaces/{self.workspace_id}/videos/", video.storage_key)
        upload.assert_called_once()

    def test_only_queued_workspace_job_can_be_cancelled(self):
        job = SimpleNamespace(status=JobStatus.QUEUED)
        db = MagicMock()
        db.scalar.side_effect = [self.connection, job]
        self.assertTrue(cancel_job_from_telegram(db, 123, uuid.uuid4()))
        self.assertEqual(job.status, JobStatus.CANCELLED)
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
