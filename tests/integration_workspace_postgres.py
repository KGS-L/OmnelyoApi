"""Tests d'isolation nécessitant une base PostgreSQL migrée."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.dependencies import get_current_workspace_membership
from api.integrations.telegram import (
    PendingTelegramLink,
    attach_telegram_account,
    get_active_telegram_connection,
    revoke_telegram_account,
)
from api.models import (
    Channel,
    ChannelPlatform,
    Job,
    JobStatus,
    JobType,
    Publication,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
    Video,
)
from api.routes.channels import _get_channel
from api.routes.jobs import _ensure_video_in_workspace, _get_job
from api.routes.publications import _ensure_targets_in_workspace, _get_publication
from api.routes.videos import _get_video, delete_video
from workers.job_state import (
    claim_next_job,
    complete_job,
    fail_job,
    heartbeat_job,
    recover_stale_jobs,
)


class PostgreSQLWorkspaceIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(get_settings().api_database_url)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection)
        suffix = uuid.uuid4().hex
        self.user_a = User(email=f"a-{suffix}@example.com", email_verified=True)
        self.user_b = User(email=f"b-{suffix}@example.com", email_verified=True)
        self.workspace_a = Workspace(name="Workspace A", slug=f"workspace-a-{suffix}")
        self.workspace_b = Workspace(name="Workspace B", slug=f"workspace-b-{suffix}")
        self.db.add_all([self.user_a, self.user_b, self.workspace_a, self.workspace_b])
        self.db.flush()
        self.db.add_all(
            [
                WorkspaceMembership(
                    workspace_id=self.workspace_a.id,
                    user_id=self.user_a.id,
                    role=WorkspaceRole.OWNER,
                ),
                WorkspaceMembership(
                    workspace_id=self.workspace_b.id,
                    user_id=self.user_b.id,
                    role=WorkspaceRole.OWNER,
                ),
            ]
        )
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def test_user_can_access_own_workspace(self):
        membership = get_current_workspace_membership(
            self.workspace_a.id, self.user_a, self.db
        )
        self.assertEqual(membership.role, WorkspaceRole.OWNER)

    def test_user_cannot_access_another_workspace(self):
        with self.assertRaises(HTTPException) as caught:
            get_current_workspace_membership(
                self.workspace_b.id, self.user_a, self.db
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_channel_query_cannot_cross_workspace_boundary(self):
        channel = Channel(
            workspace_id=self.workspace_b.id,
            platform=ChannelPlatform.YOUTUBE,
            external_id=f"youtube-{uuid.uuid4().hex}",
            name="Chaîne B",
        )
        self.db.add(channel)
        self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            _get_channel(self.db, self.workspace_a.id, channel.id)
        self.assertEqual(caught.exception.status_code, 404)

    def test_video_query_cannot_cross_workspace_boundary(self):
        video = Video(
            workspace_id=self.workspace_b.id,
            source_url="https://example.com/source.mp4",
        )
        self.db.add(video)
        self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            _get_video(self.db, self.workspace_a.id, video.id)
        self.assertEqual(caught.exception.status_code, 404)

    def test_video_with_job_cannot_be_deleted(self):
        video = Video(
            workspace_id=self.workspace_a.id,
            source_url="https://example.com/source.mp4",
        )
        self.db.add(video)
        self.db.flush()
        self.db.add(
            Job(
                workspace_id=self.workspace_a.id,
                video_id=video.id,
                type=JobType.PROCESS,
            )
        )
        self.db.flush()
        membership = get_current_workspace_membership(
            self.workspace_a.id, self.user_a, self.db
        )
        with self.assertRaises(HTTPException) as caught:
            delete_video(
                self.workspace_a.id,
                video.id,
                membership,
                self.db,
            )
        self.assertEqual(caught.exception.status_code, 409)

    def test_job_query_cannot_cross_workspace_boundary(self):
        job = Job(workspace_id=self.workspace_b.id, type=JobType.INGEST)
        self.db.add(job)
        self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            _get_job(self.db, self.workspace_a.id, job.id)
        self.assertEqual(caught.exception.status_code, 404)

    def test_job_cannot_reference_video_from_another_workspace(self):
        video = Video(
            workspace_id=self.workspace_b.id,
            source_url="https://example.com/foreign-source.mp4",
        )
        self.db.add(video)
        self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            _ensure_video_in_workspace(self.db, self.workspace_a.id, video.id)
        self.assertEqual(caught.exception.status_code, 404)

    def test_publication_query_cannot_cross_workspace_boundary(self):
        video = Video(
            workspace_id=self.workspace_b.id,
            source_url="https://example.com/published-source.mp4",
        )
        channel = Channel(
            workspace_id=self.workspace_b.id,
            platform=ChannelPlatform.YOUTUBE,
            external_id=f"youtube-{uuid.uuid4().hex}",
            name="Chaîne publication B",
        )
        self.db.add_all([video, channel])
        self.db.flush()
        publication = Publication(
            workspace_id=self.workspace_b.id,
            video_id=video.id,
            channel_id=channel.id,
            title="Publication B",
        )
        self.db.add(publication)
        self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            _get_publication(self.db, self.workspace_a.id, publication.id)
        self.assertEqual(caught.exception.status_code, 404)

    def test_publication_targets_must_share_workspace(self):
        video = Video(
            workspace_id=self.workspace_a.id,
            source_url="https://example.com/source-a.mp4",
        )
        channel = Channel(
            workspace_id=self.workspace_b.id,
            platform=ChannelPlatform.YOUTUBE,
            external_id=f"youtube-{uuid.uuid4().hex}",
            name="Chaîne étrangère",
        )
        self.db.add_all([video, channel])
        self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            _ensure_targets_in_workspace(
                self.db, self.workspace_a.id, video.id, channel.id
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_telegram_account_cannot_be_claimed_by_another_user(self):
        attach_telegram_account(
            self.db,
            PendingTelegramLink(
                user_id=self.user_a.id, workspace_id=self.workspace_a.id
            ),
            telegram_user_id=123456789,
            telegram_chat_id=123456789,
        )
        with self.assertRaises(ValueError):
            attach_telegram_account(
                self.db,
                PendingTelegramLink(
                    user_id=self.user_b.id, workspace_id=self.workspace_b.id
                ),
                telegram_user_id=123456789,
                telegram_chat_id=123456789,
            )

    def test_expired_workspace_access_blocks_telegram_link(self):
        membership = self.db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == self.workspace_a.id,
                WorkspaceMembership.user_id == self.user_a.id,
            )
        )
        self.db.delete(membership)
        self.db.flush()
        with self.assertRaises(ValueError):
            attach_telegram_account(
                self.db,
                PendingTelegramLink(
                    user_id=self.user_a.id, workspace_id=self.workspace_a.id
                ),
                telegram_user_id=987654321,
                telegram_chat_id=987654321,
            )

    def test_telegram_connection_can_be_revoked_from_bot(self):
        telegram_user_id = 456789123
        attach_telegram_account(
            self.db,
            PendingTelegramLink(
                user_id=self.user_a.id, workspace_id=self.workspace_a.id
            ),
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_user_id,
        )
        self.assertIsNotNone(
            get_active_telegram_connection(self.db, telegram_user_id)
        )
        self.assertTrue(revoke_telegram_account(self.db, telegram_user_id))
        self.assertIsNone(get_active_telegram_connection(self.db, telegram_user_id))
        self.assertFalse(revoke_telegram_account(self.db, telegram_user_id))

    def test_worker_claim_retry_and_completion(self):
        job = Job(workspace_id=self.workspace_a.id, type=JobType.INGEST)
        self.db.add(job)
        self.db.commit()
        job_id = job.id

        claimed = claim_next_job(self.db, "worker-a")
        self.assertEqual(claimed.id, job_id)
        self.assertEqual(claimed.status, JobStatus.RUNNING)
        self.assertEqual(claimed.attempts, 1)
        self.assertTrue(heartbeat_job(self.db, job_id, "worker-a"))

        status = fail_job(
            self.db, job_id, "worker-a", "Erreur temporaire", retry_delay_seconds=0
        )
        self.assertEqual(status, JobStatus.QUEUED)
        claimed = claim_next_job(self.db, "worker-b")
        self.assertEqual(claimed.id, job_id)
        self.assertEqual(claimed.attempts, 2)
        self.assertTrue(complete_job(self.db, job_id, "worker-b", {"ok": True}))
        self.db.refresh(job)
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.progress, 100)

    def test_worker_without_handler_does_not_claim_job(self):
        job = Job(workspace_id=self.workspace_a.id, type=JobType.RENDER)
        self.db.add(job)
        self.db.commit()
        self.assertIsNone(
            claim_next_job(self.db, "worker-without-handlers", frozenset())
        )
        self.db.refresh(job)
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.attempts, 0)

    def test_stale_worker_job_is_requeued(self):
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        job = Job(
            workspace_id=self.workspace_a.id,
            type=JobType.INGEST,
            status=JobStatus.RUNNING,
            attempts=1,
            worker_id="dead-worker",
            started_at=stale_time,
            heartbeat_at=stale_time,
        )
        self.db.add(job)
        self.db.commit()
        self.assertEqual(recover_stale_jobs(self.db, stale_after_seconds=300), 1)
        self.db.refresh(job)
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertIsNone(job.worker_id)


if __name__ == "__main__":
    unittest.main()
