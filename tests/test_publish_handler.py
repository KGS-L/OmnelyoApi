"""Tests du contrat du handler PUBLISH."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from api.integrations.social import PublisherCredentials
from api.models import JobType
from workers.handlers.publish import _needs_refresh, _result
from workers.registry import registry


class PublishHandlerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
