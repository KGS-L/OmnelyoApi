"""Tests de l'adaptateur Facebook Pages/Reels."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from api.integrations.facebook import FacebookPublisher
from api.integrations.social import (
    PublisherCredentials,
    PublishRequest,
    SocialErrorCode,
    SocialPublisherError,
)
from api.models import PublicationFormat, PublicationVisibility


def _graph_response(status_code, payload):
    response = Mock(status_code=status_code)
    response.json.return_value = payload
    return response


class FacebookPublisherTests(unittest.TestCase):
    def setUp(self):
        self.publisher = FacebookPublisher("app", "secret", "v23.0")

    def test_oauth_url_requests_page_permissions(self):
        url = self.publisher.connect("state-safe", "https://api.test/callback")
        self.assertIn("pages_manage_posts", url)
        self.assertIn("state-safe", url)

    @patch.object(FacebookPublisher, "_request")
    def test_oauth_returns_one_grant_per_page_token(self, request):
        request.side_effect = [
            {"access_token": "short-token"},
            {"access_token": "long-token"},
            {"data": [
                {"id": "page-a", "name": "A", "access_token": "token-a"},
                {"id": "page-b", "name": "B", "access_token": "token-b"},
            ]},
        ]
        grants = self.publisher.exchange_code("code", "https://api.test/callback")
        self.assertEqual([grant.provider_account_id for grant in grants], ["page-a", "page-b"])
        self.assertEqual(grants[1].access_token, "token-b")
        self.assertIsNone(grants[0].expires_at)

    @patch.object(FacebookPublisher, "_request")
    def test_accounts_are_fetched_with_long_lived_token_after_exchange(self, request):
        request.side_effect = [
            {"access_token": "short-token"},
            {"access_token": "long-token"},
            {"data": [{"id": "page-a", "name": "A", "access_token": "token-a"}]},
        ]
        self.publisher.exchange_code("code", "https://api.test/callback")
        long_lived_call = request.call_args_list[1]
        self.assertEqual(long_lived_call.kwargs["params"]["grant_type"], "fb_exchange_token")
        self.assertEqual(long_lived_call.kwargs["params"]["fb_exchange_token"], "short-token")
        accounts_call = request.call_args_list[2]
        self.assertEqual(accounts_call.args[1], "/me/accounts")
        self.assertEqual(accounts_call.args[2], "long-token")
        self.assertEqual(accounts_call.kwargs["params"]["limit"], 100)

    @patch.object(FacebookPublisher, "_request")
    def test_accounts_pagination_follows_cursors_and_dedupes(self, request):
        request.side_effect = [
            {"access_token": "short-token"},
            {"access_token": "long-token"},
            {
                "data": [
                    {"id": "page-a", "name": "A", "access_token": "token-a"},
                    {"id": "page-b", "name": "B", "access_token": "token-b"},
                ],
                "paging": {"cursors": {"after": "cursor-1"}, "next": "https://graph.test/next"},
            },
            {
                "data": [
                    {"id": "page-b", "name": "B", "access_token": "token-b"},
                    {"id": "page-c", "name": "C", "access_token": "token-c"},
                ],
            },
        ]
        grants = self.publisher.exchange_code("code", "https://api.test/callback")
        self.assertEqual([grant.provider_account_id for grant in grants], ["page-a", "page-b", "page-c"])
        second_accounts_call = request.call_args_list[3]
        self.assertEqual(second_accounts_call.kwargs["params"]["after"], "cursor-1")
        self.assertEqual(second_accounts_call.args[2], "long-token")

    def test_reel_requires_public_visibility(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            request = PublishRequest(
                Path(video.name), "Titre", None, PublicationVisibility.PRIVATE
            )
            with self.assertRaisesRegex(SocialPublisherError, "publique"):
                self.publisher.validate_media(request)

    @patch("api.integrations.facebook.requests.post")
    @patch.object(FacebookPublisher, "_request")
    def test_publish_starts_upload_and_finishes_reel(self, graph_request, upload):
        graph_request.side_effect = [
            {"video_id": "video-1", "upload_url": "https://upload.test/reel"},
            {"success": True},
        ]
        upload.return_value = Mock(status_code=200)
        upload.return_value.raise_for_status.return_value = None
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            result = self.publisher.publish(
                PublisherCredentials("page-token", None, [], None),
                "page-1",
                PublishRequest(
                    Path(video.name), "Titre", "Description", PublicationVisibility.PUBLIC
                ),
            )
        self.assertEqual(result.external_id, "video-1")
        self.assertEqual(result.status, "processing")
        self.assertEqual(graph_request.call_count, 2)

    @patch.object(FacebookPublisher, "_request")
    def test_carousel_uploads_unpublished_photos_then_feed(self, request):
        request.side_effect = [{"id": "photo-1"}, {"id": "photo-2"}, {"id": "post-1"}]
        with tempfile.NamedTemporaryFile(suffix=".jpg") as first, tempfile.NamedTemporaryFile(suffix=".png") as second:
            result = self.publisher.publish(
                PublisherCredentials("page-token", None, [], None), "page-1",
                PublishRequest(
                    Path(first.name), "Titre", None, PublicationVisibility.PUBLIC,
                    format=PublicationFormat.CAROUSEL,
                    media_paths=(Path(first.name), Path(second.name)),
                ),
            )
        self.assertEqual(result.external_id, "post-1")
        self.assertIn('"media_fbid": "photo-1"', request.call_args.kwargs["params"]["attached_media"])

    @patch("api.integrations.facebook.requests.request")
    def test_request_classifies_meta_error_table(self, request):
        cases = [
            # (status, payload, code attendu, retryable attendu)
            (401, {"error": {"message": "unauthorized"}}, SocialErrorCode.AUTHORIZATION, False),
            (403, {"error": {"message": "forbidden"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 190, "message": "token expiré"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 102, "message": "session expirée"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 10, "message": "permission refusée"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 2500, "error_subcode": 33}}, SocialErrorCode.AUTHORIZATION, False),
            (200, {"error": {"code": 190, "message": "token révoqué"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 4, "message": "rate limit"}}, SocialErrorCode.TEMPORARY, True),
            (400, {"error": {"code": 17, "message": "rate limit"}}, SocialErrorCode.TEMPORARY, True),
            (400, {"error": {"code": 32, "message": "rate limit"}}, SocialErrorCode.TEMPORARY, True),
            (400, {"error": {"code": 613, "message": "rate limit"}}, SocialErrorCode.TEMPORARY, True),
            (429, {"error": {"message": "trop de requêtes"}}, SocialErrorCode.TEMPORARY, True),
            (500, {"error": {"code": 2, "message": "temporairement indisponible"}}, SocialErrorCode.TEMPORARY, True),
            (400, {"error": {"code": 200, "message": "permissions"}}, SocialErrorCode.TEMPORARY, False),
        ]
        for status_code, payload, expected_code, expected_retryable in cases:
            with self.subTest(status=status_code, payload=payload):
                request.return_value = _graph_response(status_code, payload)
                with self.assertRaises(SocialPublisherError) as raised:
                    self.publisher._request("GET", "/me", "token")
                self.assertIs(raised.exception.code, expected_code)
                self.assertEqual(raised.exception.retryable, expected_retryable)

    @patch("api.integrations.facebook.requests.request")
    def test_request_returns_payload_without_error(self, request):
        request.return_value = _graph_response(200, {"id": "page-1", "name": "Page"})
        self.assertEqual(
            self.publisher._request("GET", "/me", "token"), {"id": "page-1", "name": "Page"}
        )


if __name__ == "__main__":
    unittest.main()
