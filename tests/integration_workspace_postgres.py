"""Tests d'isolation nécessitant une base PostgreSQL migrée."""
import unittest
import uuid

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.dependencies import get_current_workspace_membership
from api.integrations.telegram import PendingTelegramLink, attach_telegram_account
from api.models import (
    Channel,
    ChannelPlatform,
    Job,
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


if __name__ == "__main__":
    unittest.main()
