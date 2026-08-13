"""Tests purs des primitives de sécurité ne nécessitant aucun service externe."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api.auth.otp import EmailDeliveryError, EmailSender, OTPService


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


class EmailSenderTests(unittest.TestCase):
    def settings(self, **overrides):
        values = {
            "email_provider": "resend",
            "email_from": "ShortPilot <login@example.com>",
            "email_reply_to": "support@example.com",
            "resend_api_key": "re_test_key",
            "otp_ttl_seconds": 600,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    @patch("api.auth.otp.requests.post")
    def test_resend_receives_otp_email(self, post):
        post.return_value.raise_for_status.return_value = None

        EmailSender(self.settings()).send_otp("user@example.com", "123456")

        post.assert_called_once()
        _, kwargs = post.call_args
        self.assertEqual(kwargs["json"]["to"], ["user@example.com"])
        self.assertIn("123456", kwargs["json"]["text"])
        self.assertEqual(kwargs["timeout"], 10)
        self.assertNotIn("re_test_key", str(kwargs["json"]))

    @patch("api.auth.otp.requests.post")
    def test_provider_failure_is_normalized(self, post):
        import requests

        post.side_effect = requests.Timeout("provider timeout")
        with self.assertRaises(EmailDeliveryError):
            EmailSender(self.settings()).send_otp("user@example.com", "123456")

    @patch("api.auth.otp.requests.post")
    def test_log_provider_never_calls_network(self, post):
        EmailSender(self.settings(email_provider="log")).send_otp(
            "user@example.com", "123456"
        )
        post.assert_not_called()
