"""Tests de l'adaptateur TikTok sandbox."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from api.integrations.social import (
    PublisherCredentials,
    PublishRequest,
    SocialErrorCode,
    SocialPublisherError,
)
from api.integrations.tiktok import TikTokPublisher
from api.models import PublicationFormat, PublicationVisibility


class TikTokPublisherTests(unittest.TestCase):
    def test_authorization_url_contains_state_and_scopes(self):
        url = TikTokPublisher("key", "secret").connect("safe-state", "https://api.test/callback")
        self.assertIn("safe-state", url)
        self.assertIn("video.publish", url)

    def test_sandbox_rejects_public_visibility(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            request = PublishRequest(
                Path(video.name), "Titre", None, PublicationVisibility.PUBLIC
            )
            with self.assertRaisesRegex(SocialPublisherError, "SELF_ONLY"):
                TikTokPublisher("key", "secret").validate_media(request)

    def test_sandbox_accepts_private_mp4(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            request = PublishRequest(
                Path(video.name), "Titre", None, PublicationVisibility.PRIVATE
            )
            TikTokPublisher("key", "secret").validate_media(request)

    @patch.object(TikTokPublisher, "_request")
    def test_photo_uses_content_init_with_pull_urls(self, request):
        request.return_value = {"data": {"publish_id": "photo-1"}}
        with tempfile.NamedTemporaryFile(suffix=".jpg") as first, tempfile.NamedTemporaryFile(suffix=".png") as second:
            result = TikTokPublisher("key", "secret").publish(
                PublisherCredentials("token", None, [], None),
                "account",
                PublishRequest(
                    Path(first.name), "Titre", "Légende", PublicationVisibility.PRIVATE,
                    format=PublicationFormat.CAROUSEL,
                    media_paths=(Path(first.name), Path(second.name)),
                    media_urls=("https://cdn.test/1.jpg", "https://cdn.test/2.png"),
                ),
            )
        self.assertEqual(result.external_id, "photo-1")
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["media_type"], "PHOTO")
        self.assertEqual(payload["source_info"]["photo_images"], ["https://cdn.test/1.jpg", "https://cdn.test/2.png"])

    @patch("api.integrations.tiktok.requests.request")
    def test_request_classifies_tiktok_error_table(self, request):
        def _response(status_code, payload):
            response = Mock(status_code=status_code)
            response.json.return_value = payload
            return response

        cases = [
            # (status, payload, code attendu, retryable attendu)
            (401, {"error": "access_token_invalid", "error_description": "token invalide"},
             SocialErrorCode.AUTHORIZATION, False),
            (200, {"error": "access_token_expired", "error_description": "token expiré"},
             SocialErrorCode.AUTHORIZATION, False),
            (400, {"data": {}, "error": {"code": "access_token_invalid", "message": "invalide", "log_id": "x"}},
             SocialErrorCode.AUTHORIZATION, False),
            (400, {"data": {}, "error": {"code": "access_token_expired", "message": "expiré", "log_id": "x"}},
             SocialErrorCode.AUTHORIZATION, False),
            (429, {"error": "rate_limit_exceeded", "error_description": "trop de requêtes"},
             SocialErrorCode.TEMPORARY, True),
            (400, {"data": {}, "error": {"code": "rate_limit_exceeded", "message": "trop de requêtes", "log_id": "x"}},
             SocialErrorCode.TEMPORARY, True),
            (429, {"data": {}}, SocialErrorCode.TEMPORARY, True),
            (403, {"error": "scope_invalid", "error_description": "permission manquante"},
             SocialErrorCode.AUTHORIZATION, False),
            (500, {"data": {}, "error": {"code": "internal_error", "log_id": "x"}},
             SocialErrorCode.TEMPORARY, True),
        ]
        publisher = TikTokPublisher("key", "secret")
        for status_code, payload, expected_code, expected_retryable in cases:
            with self.subTest(status=status_code, payload=payload):
                request.return_value = _response(status_code, payload)
                with self.assertRaises(SocialPublisherError) as raised:
                    publisher._request("GET", "/v2/user/info/", PublisherCredentials("t", None, [], None))
                self.assertIs(raised.exception.code, expected_code)
                self.assertEqual(raised.exception.retryable, expected_retryable)

    @patch("api.integrations.tiktok.requests.request")
    def test_request_returns_payload_on_ok(self, request):
        response = Mock(status_code=200)
        response.json.return_value = {"data": {"user": {"open_id": "open-1"}}}
        request.return_value = response
        publisher = TikTokPublisher("key", "secret")
        self.assertEqual(
            publisher._request("GET", "/v2/user/info/", PublisherCredentials("t", None, [], None)),
            {"data": {"user": {"open_id": "open-1"}}},
        )


if __name__ == "__main__":
    unittest.main()
