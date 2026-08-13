"""Tests d'isolation nécessitant une base PostgreSQL migrée."""
import unittest
import uuid

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.config import get_settings
from api.dependencies import get_current_workspace_membership
from api.models import (
    Channel,
    ChannelPlatform,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from api.routes.channels import _get_channel


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


if __name__ == "__main__":
    unittest.main()
