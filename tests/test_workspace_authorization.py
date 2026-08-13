"""Tests des règles d'accès multi-tenant aux workspaces."""
import unittest
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from api.dependencies import ensure_workspace_role, get_current_workspace_membership
from api.models import WorkspaceMembership, WorkspaceRole


class FakeSession:
    def __init__(self, membership):
        self.membership = membership

    def scalar(self, statement):
        return self.membership


class WorkspaceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.workspace_id = uuid.uuid4()
        self.user = SimpleNamespace(id=uuid.uuid4())

    def test_member_of_workspace_is_resolved(self):
        membership = WorkspaceMembership(
            workspace_id=self.workspace_id,
            user_id=self.user.id,
            role=WorkspaceRole.MEMBER,
        )
        resolved = get_current_workspace_membership(
            self.workspace_id, self.user, FakeSession(membership)
        )
        self.assertIs(resolved, membership)

    def test_unknown_workspace_is_hidden(self):
        with self.assertRaises(HTTPException) as caught:
            get_current_workspace_membership(
                self.workspace_id, self.user, FakeSession(None)
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_admin_can_use_admin_route(self):
        membership = SimpleNamespace(role=WorkspaceRole.ADMIN)
        self.assertIs(
            ensure_workspace_role(
                membership, frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})
            ),
            membership,
        )

    def test_member_cannot_use_admin_route(self):
        membership = SimpleNamespace(role=WorkspaceRole.MEMBER)
        with self.assertRaises(HTTPException) as caught:
            ensure_workspace_role(
                membership, frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})
            )
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
