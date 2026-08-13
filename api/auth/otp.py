"""OTP email stockés sous forme hachée dans Redis."""
import hashlib
import hmac
import logging
import secrets
from html import escape
from typing import TYPE_CHECKING, Any

import requests

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


class EmailDeliveryError(RuntimeError):
    """Erreur d'envoi ne contenant ni clé fournisseur ni code OTP."""


class EmailSender:
    """Envoie les OTP via le fournisseur transactionnel configuré."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def send_otp(self, email: str, code: str) -> None:
        if self.settings.email_provider == "log":
            logger.info("OTP demandé pour %s (EMAIL_PROVIDER=log)", email)
            return
        if self.settings.email_provider != "resend":
            raise EmailDeliveryError("Fournisseur d'email non pris en charge.")
        self._send_with_resend(email, code)

    def _send_with_resend(self, email: str, code: str) -> None:
        minutes = max(1, self.settings.otp_ttl_seconds // 60)
        payload: dict[str, Any] = {
            "from": self.settings.email_from,
            "to": [email],
            "subject": f"{code} — ton code de connexion ShortPilot",
            "text": (
                f"Ton code de connexion ShortPilot est : {code}\n\n"
                f"Il expire dans {minutes} minutes. "
                "Si tu n'es pas à l'origine de cette demande, ignore cet email."
            ),
            "html": (
                '<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;'
                'color:#07162f;padding:32px">'
                '<p style="font-size:20px;font-weight:700">ShortPilot</p>'
                '<h1 style="font-size:24px">Ton code de connexion</h1>'
                f'<p style="font-size:36px;font-weight:800;letter-spacing:8px">{escape(code)}</p>'
                f'<p>Ce code expire dans {minutes} minutes.</p>'
                '<p style="color:#64748b">Si tu n’es pas à l’origine de cette demande, '
                'tu peux ignorer cet email.</p></div>'
            ),
        }
        if self.settings.email_reply_to.strip():
            payload["reply_to"] = self.settings.email_reply_to.strip()
        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.exception("Échec d'envoi de l'OTP via Resend vers %s", email)
            raise EmailDeliveryError("Le service d'email est temporairement indisponible.") from exc
