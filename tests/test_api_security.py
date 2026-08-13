"""Tests purs des primitives de sécurité ne nécessitant aucun service externe."""
import unittest
from types import SimpleNamespace

from api.auth.otp import OTPService


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    def setex(self, key, ttl, value):
        self.operations.append(("setex", key, ttl, value)); return self

    def delete(self, *keys):
        self.operations.append(("delete", keys)); return self

    def execute(self):
        for operation in self.operations:
            if operation[0] == "setex":
                _, key, _, value = operation; self.redis.values[key] = value
            else:
                for key in operation[1]: self.redis.values.pop(key, None)


class FakeRedis:
    def __init__(self):
        self.values = {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, ttl): return True
    def setex(self, key, ttl, value): self.values[key] = value
    def get(self, key):
        value = self.values.get(key)
        return value.encode() if isinstance(value, str) else value
    def delete(self, *keys):
        for key in keys: self.values.pop(key, None)
    def pipeline(self): return FakePipeline(self)


class OTPTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.settings = SimpleNamespace(
            api_jwt_secret="a-secure-test-secret-with-32-characters",
            otp_max_attempts=2,
            otp_request_limit_per_hour=2,
            otp_ttl_seconds=600,
        )
        self.service = OTPService(self.redis, self.settings)

    def test_code_is_stored_hashed_and_single_use(self):
        code = self.service.issue("User@Example.com")
        stored = self.redis.values["otp:code:user@example.com"]
        self.assertNotEqual(stored, code)
        self.assertTrue(self.service.verify("user@example.com", code))
        self.assertFalse(self.service.verify("user@example.com", code))

    def test_rate_limit(self):
        self.service.issue("user@example.com")
        self.service.issue("user@example.com")
        with self.assertRaises(ValueError):
            self.service.issue("user@example.com")
