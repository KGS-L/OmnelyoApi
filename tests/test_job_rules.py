"""Validation des entrées et transitions de jobs."""
import unittest
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError

from api.models import JobStatus, JobType
from api.routes.jobs import cancel_job_record, retry_job_record
from api.schemas import JobCreate


class JobSchemaTests(unittest.TestCase):
    def test_process_job_requires_video(self):
        with self.assertRaises(ValidationError):
            JobCreate(type=JobType.PROCESS)

    def test_ingest_job_can_create_the_video(self):
        payload = JobCreate(type=JobType.INGEST, payload={"source_url": "https://example.com"})
        self.assertIsNone(payload.video_id)

    def test_process_job_accepts_video(self):
        video_id = uuid.uuid4()
        payload = JobCreate(type=JobType.PROCESS, video_id=video_id)
        self.assertEqual(payload.video_id, video_id)


class JobTransitionTests(unittest.TestCase):
    def test_queued_job_can_be_cancelled(self):
        job = SimpleNamespace(status=JobStatus.QUEUED, finished_at=None, worker_id=None)
        cancel_job_record(job)
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertIsNotNone(job.finished_at)

    def test_running_job_cannot_be_cancelled_by_api(self):
        job = SimpleNamespace(status=JobStatus.RUNNING, finished_at=None)
        with self.assertRaises(HTTPException) as caught:
            cancel_job_record(job)
        self.assertEqual(caught.exception.status_code, 409)

    def test_failed_job_can_be_retried(self):
        job = SimpleNamespace(
            status=JobStatus.FAILED,
            attempts=1,
            max_attempts=3,
            progress=75,
            error_message="Erreur temporaire",
            available_at=None,
            started_at=object(),
            heartbeat_at=object(),
            worker_id="worker-1",
            finished_at=object(),
            result={"partial": True},
        )
        retry_job_record(job)
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.progress, 0)
        self.assertIsNone(job.error_message)
        self.assertIsNone(job.result)
        self.assertIsNone(job.worker_id)

    def test_exhausted_job_cannot_be_retried(self):
        job = SimpleNamespace(status=JobStatus.FAILED, attempts=3, max_attempts=3)
        with self.assertRaises(HTTPException) as caught:
            retry_job_record(job)
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
