"""Tests d'isolation nécessitant une base PostgreSQL migrée."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.config import get_settings
from api.dependencies import get_current_workspace_membership
from api.integrations.telegram import (
    PendingTelegramLink,
    attach_telegram_account,
    get_active_telegram_connection,
    revoke_telegram_account,
)
from api.integrations.social import OAuthGrant, SocialChannel
from api.integrations.social_oauth import PendingSocialOAuth, persist_oauth_grant
from api.models import (
    Channel,
    ChannelPlatform,
    Job,
    JobStatus,
    JobType,
    Publication,
    PublicationVisibility,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
    Video,
    VideoKind,
)
from api.routes.channels import _get_channel
from api.routes.jobs import _ensure_video_in_workspace, _get_job
from api.routes.publications import (
    _ensure_targets_in_workspace,
    _get_publication,
    enqueue_publication_record,
    enqueue_batch_publication_records,
    create_batch_publication_records,
)
from api.schemas import PublicationBatchCreate, PublicationDestinationCreate
from api.routes.videos import _get_video, delete_video
from api.security.social_credentials import SocialCredentialCipher
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

    def test_oauth_grant_is_encrypted_and_creates_workspace_channel(self):
        cipher = SocialCredentialCipher(Fernet.generate_key().decode("ascii"))
        connection, channels = persist_oauth_grant(
            self.db,
            PendingSocialOAuth(
                user_id=self.user_a.id,
                workspace_id=self.workspace_a.id,
                platform=ChannelPlatform.INSTAGRAM,
            ),
            OAuthGrant(
                provider_account_id="meta-account",
                access_token="access-secret",
                refresh_token="refresh-secret",
                scopes=["content_publish", "content_publish"],
                expires_at=None,
                channels=[SocialChannel(external_id="ig-account", name="Compte IG")],
            ),
            cipher,
        )
        self.assertNotIn("access-secret", connection.access_token_encrypted)
        self.assertEqual(cipher.decrypt(connection.access_token_encrypted), "access-secret")
        self.assertEqual(connection.scopes, ["content_publish"])
        self.assertEqual(channels[0].workspace_id, self.workspace_a.id)
        self.assertEqual(channels[0].connection_id, connection.id)

    def test_ready_publication_is_enqueued_only_once(self):
        cipher = SocialCredentialCipher(Fernet.generate_key().decode("ascii"))
        _, channels = persist_oauth_grant(
            self.db,
            PendingSocialOAuth(
                user_id=self.user_a.id,
                workspace_id=self.workspace_a.id,
                platform=ChannelPlatform.YOUTUBE,
            ),
            OAuthGrant(
                provider_account_id="youtube-account",
                access_token="access-secret",
                refresh_token="refresh-secret",
                scopes=["youtube.upload"],
                expires_at=None,
                channels=[SocialChannel(external_id="youtube-channel", name="YouTube")],
            ),
            cipher,
        )
        video = Video(
            workspace_id=self.workspace_a.id,
            title="Clip rendu",
            rendered_storage_key="workspaces/a/rendered/clip.mp4",
            duration_seconds=60,
        )
        self.db.add(video)
        self.db.flush()
        publication = Publication(
            workspace_id=self.workspace_a.id,
            video_id=video.id,
            channel_id=channels[0].id,
            title="Publication",
        )
        self.db.add(publication)
        self.db.commit()
        first = enqueue_publication_record(self.db, self.workspace_a.id, publication)
        second = enqueue_publication_record(self.db, self.workspace_a.id, publication)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.type, JobType.PUBLISH)
        self.assertEqual(first.payload["publication_id"], str(publication.id))

    def test_batch_creates_independent_publication_per_destination(self):
        cipher = SocialCredentialCipher(Fernet.generate_key().decode("ascii"))
        _, channels = persist_oauth_grant(
            self.db,
            PendingSocialOAuth(
                user_id=self.user_a.id,
                workspace_id=self.workspace_a.id,
                platform=ChannelPlatform.YOUTUBE,
            ),
            OAuthGrant(
                provider_account_id="batch-youtube-account",
                access_token="batch-access",
                refresh_token="batch-refresh",
                scopes=["youtube.upload"],
                expires_at=None,
                channels=[
                    SocialChannel(external_id="batch-channel-1", name="Chaîne 1"),
                    SocialChannel(external_id="batch-channel-2", name="Chaîne 2"),
                ],
            ),
            cipher,
        )
        video = Video(
            workspace_id=self.workspace_a.id,
            title="Vidéo multi-destination",
            rendered_storage_key="workspaces/a/rendered/batch.mp4",
            duration_seconds=60,
        )
        self.db.add(video)
        self.db.flush()
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=2)
        publications = create_batch_publication_records(
            self.db,
            self.workspace_a.id,
            PublicationBatchCreate(
                video_id=video.id,
                destinations=[
                    PublicationDestinationCreate(
                        channel_id=channels[0].id,
                        title="Titre immédiat",
                    ),
                    PublicationDestinationCreate(
                        channel_id=channels[1].id,
                        title="Titre programmé",
                        visibility=PublicationVisibility.PUBLIC,
                        scheduled_at=scheduled_at,
                    ),
                ],
            ),
        )
        self.assertEqual(len(publications), 2)
        self.assertNotEqual(publications[0].id, publications[1].id)
        self.assertEqual(
            {publication.channel_id for publication in publications},
            {channels[0].id, channels[1].id},
        )
        self.assertEqual(publications[0].status.value, "draft")
        self.assertEqual(publications[1].status.value, "scheduled")
        count_before = len(
            list(
                self.db.scalars(
                    select(Publication).where(
                        Publication.workspace_id == self.workspace_a.id,
                        Publication.video_id == video.id,
                    )
                )
            )
        )
        with self.assertRaises(HTTPException):
            create_batch_publication_records(
                self.db,
                self.workspace_a.id,
                PublicationBatchCreate(
                    video_id=video.id,
                    destinations=[
                        PublicationDestinationCreate(
                            channel_id=channels[0].id,
                            title="Destination valide",
                        ),
                        PublicationDestinationCreate(
                            channel_id=uuid.uuid4(),
                            title="Destination inconnue",
                        ),
                    ],
                ),
            )
        count_after = len(
            list(
                self.db.scalars(
                    select(Publication).where(
                        Publication.workspace_id == self.workspace_a.id,
                        Publication.video_id == video.id,
                    )
                )
            )
        )
        self.assertEqual(count_after, count_before)
        with self.assertRaises(HTTPException):
            enqueue_batch_publication_records(
                self.db,
                self.workspace_a.id,
                [publications[0].id, uuid.uuid4()],
            )
        self.assertEqual(
            len(
                list(
                    self.db.scalars(
                        select(Job).where(
                            Job.workspace_id == self.workspace_a.id,
                            Job.video_id == video.id,
                            Job.type == JobType.PUBLISH,
                        )
                    )
                )
            ),
            0,
        )
        video.duration_seconds = 181
        self.db.commit()
        with self.assertRaises(HTTPException) as invalid_media:
            enqueue_batch_publication_records(
                self.db,
                self.workspace_a.id,
                [publications[0].id, publications[1].id],
            )
        self.assertEqual(invalid_media.exception.status_code, 422)
        self.assertEqual(
            len(
                list(
                    self.db.scalars(
                        select(Job).where(
                            Job.workspace_id == self.workspace_a.id,
                            Job.video_id == video.id,
                            Job.type == JobType.PUBLISH,
                        )
                    )
                )
            ),
            0,
        )
        video.duration_seconds = 60
        self.db.commit()
        jobs = enqueue_batch_publication_records(
            self.db,
            self.workspace_a.id,
            [publications[0].id, publications[1].id],
        )
        replayed = enqueue_batch_publication_records(
            self.db,
            self.workspace_a.id,
            [publications[0].id, publications[1].id],
        )
        self.assertEqual(len(jobs), 2)
        self.assertNotEqual(jobs[0].id, jobs[1].id)
        self.assertEqual([job.id for job in replayed], [job.id for job in jobs])
        self.assertTrue(all(job.type is JobType.PUBLISH for job in jobs))

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

    def test_database_rejects_job_video_from_another_workspace(self):
        video = Video(
            workspace_id=self.workspace_b.id,
            source_url="https://example.com/foreign-job-source.mp4",
        )
        self.db.add(video)
        self.db.flush()
        with self.assertRaises(IntegrityError):
            with self.db.begin_nested():
                self.db.add(
                    Job(
                        workspace_id=self.workspace_a.id,
                        video_id=video.id,
                        type=JobType.PROCESS,
                    )
                )
                self.db.flush()

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

    def test_database_rejects_publication_graph_from_another_workspace(self):
        video = Video(
            workspace_id=self.workspace_a.id,
            source_url="https://example.com/database-source-a.mp4",
        )
        channel = Channel(
            workspace_id=self.workspace_b.id,
            platform=ChannelPlatform.YOUTUBE,
            external_id=f"youtube-db-{uuid.uuid4().hex}",
            name="Chaîne étrangère DB",
        )
        foreign_job = Job(workspace_id=self.workspace_b.id, type=JobType.INGEST)
        self.db.add_all([video, channel, foreign_job])
        self.db.flush()
        with self.assertRaises(IntegrityError):
            with self.db.begin_nested():
                self.db.add(
                    Publication(
                        workspace_id=self.workspace_a.id,
                        video_id=video.id,
                        channel_id=channel.id,
                        job_id=foreign_job.id,
                        title="Référence interdite",
                    )
                )
                self.db.flush()

    def test_database_rejects_clip_parent_from_another_workspace(self):
        parent = Video(
            workspace_id=self.workspace_b.id,
            source_url="https://example.com/foreign-parent.mp4",
        )
        self.db.add(parent)
        self.db.flush()
        with self.assertRaises(IntegrityError):
            with self.db.begin_nested():
                self.db.add(
                    Video(
                        workspace_id=self.workspace_a.id,
                        kind=VideoKind.CLIP,
                        parent_video_id=parent.id,
                        sequence_order=1,
                        storage_key="clips/foreign-parent.mp4",
                    )
                )
                self.db.flush()

    def test_database_rejects_channel_connection_from_another_workspace(self):
        cipher = SocialCredentialCipher(Fernet.generate_key().decode("ascii"))
        connection, _ = persist_oauth_grant(
            self.db,
            PendingSocialOAuth(
                user_id=self.user_b.id,
                workspace_id=self.workspace_b.id,
                platform=ChannelPlatform.FACEBOOK,
            ),
            OAuthGrant(
                provider_account_id="foreign-meta-account",
                access_token="foreign-access",
                refresh_token=None,
                scopes=[],
                expires_at=None,
                channels=[],
            ),
            cipher,
        )
        with self.assertRaises(IntegrityError):
            with self.db.begin_nested():
                self.db.add(
                    Channel(
                        workspace_id=self.workspace_a.id,
                        connection_id=connection.id,
                        platform=ChannelPlatform.FACEBOOK,
                        external_id=f"foreign-page-{uuid.uuid4().hex}",
                        name="Page étrangère",
                    )
                )
                self.db.flush()

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

    def test_clip_sequence_is_unique_per_source(self):
        source = Video(
            workspace_id=self.workspace_a.id,
            kind=VideoKind.SOURCE,
            source_url="https://example.com/source.mp4",
        )
        self.db.add(source)
        self.db.flush()
        self.db.add(
            Video(
                workspace_id=self.workspace_a.id,
                kind=VideoKind.CLIP,
                parent_video_id=source.id,
                sequence_order=1,
                storage_key="clips/one.mp4",
            )
        )
        self.db.flush()
        with self.assertRaises(IntegrityError):
            with self.db.begin_nested():
                self.db.add(
                    Video(
                        workspace_id=self.workspace_a.id,
                        kind=VideoKind.CLIP,
                        parent_video_id=source.id,
                        sequence_order=1,
                        storage_key="clips/duplicate.mp4",
                    )
                )
                self.db.flush()

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
