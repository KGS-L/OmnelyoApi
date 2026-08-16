"""Tests du contrat du handler PUBLISH."""
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

from api.integrations.social import (
    PublishResult,
    PublisherCredentials,
    SocialErrorCode,
    SocialPublisherError,
    SocialPublisherRegistry,
)
from api.models import (
    ChannelPlatform,
    ChannelStatus,
    JobType,
    PublicationFormat,
    PublicationStatus,
    PublicationVisibility,
    SocialConnectionStatus,
)
from workers.handlers.publish import (
    FAILED_PROVIDER_STATUSES,
    PUBLISHED_PROVIDER_STATUSES,
    PublishContext,
    _call_with_reactive_refresh,
    _needs_refresh,
    _persist_reconciliation,
    _quarantine_connection,
    _refresh_and_persist,
    _refresh_credentials_locked,
    _result,
    _tiktok_media_urls,
    publish_video,
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

    def test_authorization_failure_triggers_single_refresh_and_retry(self):
        connection_id = uuid.uuid4()
        publisher = MagicMock()
        refreshed = PublisherCredentials("new-token", "refresh", [], None)
        stale = PublisherCredentials("old-token", None, [], None)
        used_tokens = []

        def operation(credentials):
            used_tokens.append(credentials.access_token)
            if len(used_tokens) == 1:
                raise SocialPublisherError(
                    SocialErrorCode.AUTHORIZATION, "Meta a refusé l'opération."
                )
            return "publish_complete"

        with patch(
            "workers.handlers.publish._refresh_credentials_locked",
            return_value=refreshed,
        ) as locked:
            result = _call_with_reactive_refresh(
                publisher, connection_id, stale, "key", operation
            )
        self.assertEqual(result, "publish_complete")
        self.assertEqual(used_tokens, ["old-token", "new-token"])
        locked.assert_called_once_with(connection_id, publisher, stale, "key")

    def test_authorization_refresh_failure_quarantines_and_reraises_original(self):
        connection_id = uuid.uuid4()
        publisher = MagicMock()

        def operation(credentials):
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION, "Le token a été révoqué."
            )

        with patch("workers.handlers.publish._quarantine_connection") as quarantine, \
                patch(
                    "workers.handlers.publish._refresh_credentials_locked",
                    side_effect=SocialPublisherError(
                        SocialErrorCode.AUTHORIZATION, "La connexion doit être renouvelée."
                    ),
                ):
            with self.assertRaises(SocialPublisherError) as raised:
                _call_with_reactive_refresh(
                    publisher,
                    connection_id,
                    PublisherCredentials("old-token", None, [], None),
                    "key",
                    operation,
                )
        self.assertEqual(str(raised.exception), "Le token a été révoqué.")
        quarantine.assert_called_once_with(connection_id)

    def test_transient_refresh_failure_does_not_quarantine(self):
        connection_id = uuid.uuid4()
        publisher = MagicMock()

        def operation(credentials):
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION, "Le token a été révoqué."
            )

        with patch("workers.handlers.publish._quarantine_connection") as quarantine, \
                patch(
                    "workers.handlers.publish._refresh_credentials_locked",
                    side_effect=SocialPublisherError(
                        SocialErrorCode.NETWORK, "Meta est inaccessible.", retryable=True
                    ),
                ):
            with self.assertRaises(SocialPublisherError) as raised:
                _call_with_reactive_refresh(
                    publisher,
                    connection_id,
                    PublisherCredentials("old-token", None, [], None),
                    "key",
                    operation,
                )
        self.assertEqual(str(raised.exception), "Le token a été révoqué.")
        quarantine.assert_not_called()

    def test_non_authorization_failures_skip_refresh(self):
        publisher = MagicMock()

        def operation(credentials):
            raise SocialPublisherError(
                SocialErrorCode.TEMPORARY, "TikTok est momentanément saturé.", retryable=True
            )

        with patch("workers.handlers.publish._quarantine_connection") as quarantine:
            with self.assertRaises(SocialPublisherError) as raised:
                _call_with_reactive_refresh(
                    publisher,
                    uuid.uuid4(),
                    PublisherCredentials("old-token", None, [], None),
                    "key",
                    operation,
                )
        self.assertTrue(raised.exception.retryable)
        publisher.refresh_credentials.assert_not_called()
        quarantine.assert_not_called()

    def test_second_authorization_failure_quarantines_without_refreshing_again(self):
        connection_id = uuid.uuid4()
        publisher = MagicMock()
        refreshed = PublisherCredentials("new-token", None, [], None)
        attempts = []

        def operation(credentials):
            attempts.append(credentials.access_token)
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION, f"refus {len(attempts)}"
            )

        with patch("workers.handlers.publish._quarantine_connection") as quarantine, \
                patch(
                    "workers.handlers.publish._refresh_credentials_locked",
                    return_value=refreshed,
                ) as locked:
            with self.assertRaises(SocialPublisherError) as raised:
                _call_with_reactive_refresh(
                    publisher,
                    connection_id,
                    PublisherCredentials("old-token", None, [], None),
                    "key",
                    operation,
                )
        self.assertEqual(str(raised.exception), "refus 2")
        self.assertEqual(attempts, ["old-token", "new-token"])
        locked.assert_called_once()
        quarantine.assert_called_once_with(connection_id)

    def test_proactive_refresh_failure_quarantines_and_raises(self):
        publisher = MagicMock()
        with patch("workers.handlers.publish._quarantine_connection") as quarantine, \
                patch(
                    "workers.handlers.publish._refresh_credentials_locked",
                    side_effect=SocialPublisherError(
                        SocialErrorCode.AUTHORIZATION, "La connexion doit être renouvelée."
                    ),
                ):
            with self.assertRaises(SocialPublisherError):
                _refresh_and_persist(
                    publisher,
                    uuid.uuid4(),
                    PublisherCredentials("old-token", "refresh", [], None),
                    "key",
                )
        quarantine.assert_called_once()

    def test_proactive_transient_refresh_failure_does_not_quarantine(self):
        publisher = MagicMock()
        with patch("workers.handlers.publish._quarantine_connection") as quarantine, \
                patch(
                    "workers.handlers.publish._refresh_credentials_locked",
                    side_effect=SocialPublisherError(
                        SocialErrorCode.NETWORK, "Meta est inaccessible.", retryable=True
                    ),
                ):
            with self.assertRaises(SocialPublisherError):
                _refresh_and_persist(
                    publisher,
                    uuid.uuid4(),
                    PublisherCredentials("old-token", "refresh", [], None),
                    "key",
                )
        quarantine.assert_not_called()

    def test_proactive_refresh_returns_persisted_credentials(self):
        connection_id = uuid.uuid4()
        publisher = MagicMock()
        refreshed = PublisherCredentials("new-token", None, [], None)
        stale = PublisherCredentials("old-token", "refresh", [], None)
        with patch(
            "workers.handlers.publish._refresh_credentials_locked",
            return_value=refreshed,
        ) as locked:
            result = _refresh_and_persist(publisher, connection_id, stale, "key")
        self.assertIs(result, refreshed)
        locked.assert_called_once_with(connection_id, publisher, stale, "key")

    def test_locked_refresh_persists_encrypted_credentials(self):
        key = Fernet.generate_key().decode()
        cipher = Fernet(key)
        expiry = datetime.now(timezone.utc) + timedelta(minutes=1)
        connection = SimpleNamespace(
            access_token_encrypted=cipher.encrypt(b"old-token").decode(),
            refresh_token_encrypted=cipher.encrypt(b"old-refresh").decode(),
            scopes=["a"],
            expires_at=expiry,
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = connection
        session = MagicMock()
        session.__enter__.return_value = db
        publisher = MagicMock()
        publisher.refresh_credentials.return_value = PublisherCredentials(
            "new-token", "new-refresh", ["a"], None
        )
        current = PublisherCredentials("old-token", "old-refresh", ["a"], expiry)
        with patch("workers.handlers.publish.SessionLocal", return_value=session):
            result = _refresh_credentials_locked(
                uuid.uuid4(), publisher, current, key
            )
        self.assertEqual(result.access_token, "new-token")
        self.assertEqual(result.refresh_token, "new-refresh")
        self.assertEqual(
            cipher.decrypt(connection.access_token_encrypted.encode()).decode(),
            "new-token",
        )
        self.assertEqual(
            cipher.decrypt(connection.refresh_token_encrypted.encode()).decode(),
            "new-refresh",
        )
        self.assertIsNotNone(connection.last_verified_at)
        db.commit.assert_called_once()
        publisher.refresh_credentials.assert_called_once_with(current)

    def test_locked_refresh_adopts_recently_persisted_credentials(self):
        key = Fernet.generate_key().decode()
        cipher = Fernet(key)
        connection = SimpleNamespace(
            access_token_encrypted=cipher.encrypt(b"winner-token").decode(),
            refresh_token_encrypted=None,
            scopes=[],
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = connection
        session = MagicMock()
        session.__enter__.return_value = db
        publisher = MagicMock()
        stale = PublisherCredentials(
            "old-token", "old-refresh", [], datetime.now(timezone.utc)
        )
        with patch("workers.handlers.publish.SessionLocal", return_value=session):
            result = _refresh_credentials_locked(
                uuid.uuid4(), publisher, stale, key
            )
        self.assertEqual(result.access_token, "winner-token")
        self.assertIsNone(result.refresh_token)
        publisher.refresh_credentials.assert_not_called()
        db.commit.assert_not_called()

    def test_publish_video_refreshes_reactively_and_retries_with_new_token(self):
        publisher = MagicMock()
        publisher.platform = ChannelPlatform.FACEBOOK
        publisher.publish.side_effect = [
            SocialPublisherError(
                SocialErrorCode.AUTHORIZATION, "Meta a refusé l'opération."
            ),
            PublishResult("ext-1", "published", datetime.now(timezone.utc), {}),
        ]
        local_registry = SocialPublisherRegistry()
        local_registry.register(publisher)
        connection_id = uuid.uuid4()
        context = PublishContext(
            publication_id=uuid.uuid4(),
            connection_id=connection_id,
            platform=ChannelPlatform.FACEBOOK,
            channel_external_id="page-1",
            storage_keys=("workspaces/w/videos/rendu.mp4",),
            format=PublicationFormat.SHORT_VIDEO,
            title="Titre",
            description=None,
            visibility=PublicationVisibility.PUBLIC,
            scheduled_at=None,
            existing_external_id=None,
        )
        job = SimpleNamespace(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            payload={"publication_id": str(context.publication_id)},
        )
        publication = SimpleNamespace(
            external_id=None,
            provider_response=None,
            error_message=None,
            status=None,
            published_at=None,
        )
        db = MagicMock()
        db.get.return_value = publication
        session = MagicMock()
        session.__enter__.return_value = db
        stale = PublisherCredentials("old-token", None, [], None)
        refreshed = PublisherCredentials("new-token", None, [], None)
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "workers.handlers.publish._load_context", return_value=context
            ), patch(
                "workers.handlers.publish._load_credentials", return_value=stale
            ), patch(
                "workers.handlers.publish.register_default_publishers"
            ), patch(
                "workers.handlers.publish.social_publishers", local_registry
            ), patch(
                "workers.handlers.publish._refresh_credentials_locked",
                return_value=refreshed,
            ) as locked, patch(
                "workers.handlers.publish.SessionLocal", return_value=session
            ), patch(
                "core.storage_r2.download_from_r2"
            ), patch("config.TMP_DIR", Path(tmp_dir)):
                result = publish_video(job, lambda progress=None: True)
        tokens = [
            call.args[0].access_token for call in publisher.publish.call_args_list
        ]
        self.assertEqual(tokens, ["old-token", "new-token"])
        self.assertEqual(result["external_id"], "ext-1")
        self.assertEqual(publication.status, PublicationStatus.PUBLISHED)
        self.assertEqual(publication.external_id, "ext-1")
        locked.assert_called_once()
        self.assertEqual(locked.call_args.args[0], connection_id)

    def test_quarantine_marks_connection_expired_and_channels_disconnected(self):
        connection_id = uuid.uuid4()
        connection = SimpleNamespace(
            id=connection_id,
            workspace_id=uuid.uuid4(),
            status=SocialConnectionStatus.ACTIVE,
        )
        channel = SimpleNamespace(status=ChannelStatus.ACTIVE)
        db = MagicMock()
        db.get.return_value = connection
        db.scalars.return_value = [channel]
        session = MagicMock()
        session.__enter__.return_value = db
        with patch("workers.handlers.publish.SessionLocal", return_value=session):
            _quarantine_connection(connection_id)
        self.assertIs(connection.status, SocialConnectionStatus.EXPIRED)
        self.assertIs(channel.status, ChannelStatus.DISCONNECTED)
        db.commit.assert_called_once()

    def test_quarantine_keeps_non_active_connections_untouched(self):
        connection = SimpleNamespace(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            status=SocialConnectionStatus.REVOKED,
        )
        db = MagicMock()
        db.get.return_value = connection
        session = MagicMock()
        session.__enter__.return_value = db
        with patch("workers.handlers.publish.SessionLocal", return_value=session):
            _quarantine_connection(connection.id)
        self.assertIs(connection.status, SocialConnectionStatus.REVOKED)
        db.commit.assert_not_called()

    def test_quarantine_is_best_effort(self):
        with patch(
            "workers.handlers.publish.SessionLocal", side_effect=RuntimeError("db down")
        ):
            _quarantine_connection(uuid.uuid4())


if __name__ == "__main__":
    unittest.main()
