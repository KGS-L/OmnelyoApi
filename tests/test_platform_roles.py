import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from api.dependencies import require_platform_roles
from api.models import PlatformRole, User


class PlatformRoleTests(unittest.TestCase):
    def test_user_role_is_distinct_and_defaults_to_user(self):
        self.assertIn("platform_role", User.__table__.c)
        self.assertEqual(User.__table__.c.platform_role.server_default.arg, "user")

    def test_platform_admin_dependency_rejects_regular_user(self):
        dependency = require_platform_roles(PlatformRole.ADMIN)
        with self.assertRaises(HTTPException) as raised:
            dependency(SimpleNamespace(platform_role=PlatformRole.USER))
        self.assertEqual(raised.exception.status_code, 403)

    def test_platform_admin_dependency_accepts_admin(self):
        admin = SimpleNamespace(platform_role=PlatformRole.ADMIN)
        self.assertIs(require_platform_roles(PlatformRole.ADMIN)(admin), admin)


if __name__ == "__main__":
    unittest.main()
