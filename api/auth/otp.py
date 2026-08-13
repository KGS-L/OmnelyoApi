"""OTP email stockés sous forme hachée dans Redis."""
import hashlib
import hmac
import logging
import secrets
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis import Redis
    from api.config import APISettings

logger = logging.getLogger(__name__)


class OTPService:
    def __init__(self, redis: Any, settings: Any) -> None:
        self.redis = redis
        self.settings = settings

    def issue(self, email: str) -> str:
        normalized = email.strip().lower()
        rate_key = f"otp:rate:{normalized}"
        requests = self.redis.incr(rate_key)
        if requests == 1:
            self.redis.expire(rate_key, 3600)
        if requests > self.settings.otp_request_limit_per_hour:
            raise ValueError("Trop de demandes de code. Réessaie plus tard.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest = self._hash(normalized, code)
        pipe = self.redis.pipeline()
        pipe.setex(f"otp:code:{normalized}", self.settings.otp_ttl_seconds, digest)
        pipe.delete(f"otp:attempts:{normalized}")
        pipe.execute()
        return code

    def verify(self, email: str, code: str) -> bool:
        normalized = email.strip().lower()
        attempts_key = f"otp:attempts:{normalized}"
        attempts = self.redis.incr(attempts_key)
        if attempts == 1:
            self.redis.expire(attempts_key, self.settings.otp_ttl_seconds)
        if attempts > self.settings.otp_max_attempts:
            self.redis.delete(f"otp:code:{normalized}")
            raise ValueError("Nombre maximal de tentatives dépassé.")
        expected = self.redis.get(f"otp:code:{normalized}")
        if not expected or not hmac.compare_digest(expected.decode(), self._hash(normalized, code)):
            return False
        self.redis.delete(f"otp:code:{normalized}", attempts_key)
        return True

    def _hash(self, email: str, code: str) -> str:
        secret = self.settings.api_jwt_secret.encode()
        return hmac.new(secret, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


class EmailSender:
    """Interface minimale ; le MVP journalise sans exposer le code en production."""

    def send_otp(self, email: str, code: str) -> None:
        logger.info("OTP demandé pour %s (branche un fournisseur email avant production)", email)
