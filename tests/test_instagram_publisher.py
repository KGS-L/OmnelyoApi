"""Tests de l'adaptateur Instagram professionnel."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from api.integrations.instagram import InstagramPublisher
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


class InstagramPublisherTests(unittest.TestCase):
    def setUp(self):
        self.publisher = InstagramPublisher("app", "secret", "v23.0")

    @patch.object(InstagramPublisher, "_request")
    def test_oauth_discovers_only_pages_with_professional_account(self, request):
        request.side_effect = [
            {"access_token": "short-token"},
            {"access_token": "long-token"},
            {"data": [
                {"id": "page-empty", "name": "Sans Instagram", "access_token": "p0"},
                {"id": "page-1", "name": "Page", "access_token": "page-token",
                 "instagram_business_account": {"id": "ig-1", "username": "shortpilot"}},
            ]},
        ]
        grants = self.publisher.exchange_code("code", "https://api.test/callback")
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].provider_account_id, "ig-1")
        self.assertEqual(grants[0].access_token, "page-token")
        self.assertIsNone(grants[0].expires_at)
        self.assertEqual(grants[0].provider_metadata["facebook_page_id"], "page-1")

    @patch.object(InstagramPublisher, "_request")
    def test_accounts_are_fetched_with_long_lived_token_after_exchange(self, request):
        request.side_effect = [
            {"access_token": "short-token"},
            {"access_token": "long-token"},
            {"data": []},
        ]
        self.publisher.exchange_code("code", "https://api.test/callback")
        long_lived_call = request.call_args_list[1]
        self.assertEqual(long_lived_call.kwargs["params"]["grant_type"], "fb_exchange_token")
        self.assertEqual(long_lived_call.kwargs["params"]["fb_exchange_token"], "short-token")
        accounts_call = request.call_args_list[2]
        self.assertEqual(accounts_call.args[1], "/me/accounts")
        self.assertEqual(accounts_call.args[2], "long-token")
        self.assertEqual(accounts_call.kwargs["params"]["limit"], 100)
        self.assertIn("instagram_business_account", accounts_call.kwargs["params"]["fields"])

    @patch.object(InstagramPublisher, "_request")
    def test_accounts_pagination_follows_cursors_and_dedupes(self, request):
        request.side_effect = [
            {"access_token": "short-token"},
            {"access_token": "long-token"},
            {
                "data": [
                    {"id": "page-1", "name": "Page", "access_token": "token-1",
                     "instagram_business_account": {"id": "ig-1", "username": "un"}},
                ],
                "paging": {"cursors": {"after": "cursor-1"}, "next": "https://graph.test/next"},
            },
            {
                "data": [
                    {"id": "page-1", "name": "Page", "access_token": "token-1",
                     "instagram_business_account": {"id": "ig-1", "username": "un"}},
                    {"id": "page-2", "name": "Autre", "access_token": "token-2",
                     "instagram_business_account": {"id": "ig-2", "username": "deux"}},
                ],
            },
        ]
        grants = self.publisher.exchange_code("code", "https://api.test/callback")
        self.assertEqual([grant.provider_account_id for grant in grants], ["ig-1", "ig-2"])
        second_accounts_call = request.call_args_list[3]
        self.assertEqual(second_accounts_call.kwargs["params"]["after"], "cursor-1")

    @patch.object(InstagramPublisher, "_request")
    def test_list_channels_returns_instagram_account_of_the_page(self, request):
        request.return_value = {
            "id": "page-1",
            "name": "Page",
            "picture": {"data": {"url": "https://cdn.test/page.png"}},
            "instagram_business_account": {
                "id": "ig-1",
                "username": "shortpilot",
                "profile_picture_url": "https://cdn.test/ig.png",
            },
        }
        channels = self.publisher.list_channels(PublisherCredentials("page-token", None, [], None))
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].external_id, "ig-1")
        self.assertEqual(channels[0].handle, "shortpilot")
        self.assertEqual(channels[0].avatar_url, "https://cdn.test/ig.png")
        self.assertEqual(request.call_args.args[1], "/me")

    @patch.object(InstagramPublisher, "_request")
    def test_list_channels_returns_empty_without_instagram_account(self, request):
        request.return_value = {"id": "page-1", "name": "Page", "picture": {}}
        channels = self.publisher.list_channels(PublisherCredentials("page-token", None, [], None))
        self.assertEqual(channels, [])

    def test_reel_requires_https_media_url(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            with self.assertRaisesRegex(SocialPublisherError, "URL HTTPS"):
                self.publisher.validate_media(PublishRequest(
                    Path(video.name), "Titre", None, PublicationVisibility.PUBLIC
                ))

    @patch("api.integrations.instagram.time.sleep")
    @patch.object(InstagramPublisher, "_request")
    def test_reel_container_is_published_after_processing(self, request, sleep):
        request.side_effect = [
            {"id": "container-1"},
            {"status_code": "IN_PROGRESS"},
            {"status_code": "FINISHED"},
            {"id": "media-1"},
        ]
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            result = self.publisher.publish(
                PublisherCredentials("page-token", None, [], None),
                "ig-1",
                PublishRequest(
                    Path(video.name), "Titre", "Légende", PublicationVisibility.PUBLIC,
                    media_url="https://signed.example/reel.mp4?sig=x",
                ),
            )
        self.assertEqual(result.external_id, "media-1")
        self.assertEqual(result.raw_response["container_id"], "container-1")
        sleep.assert_called_once_with(3)

    @patch.object(InstagramPublisher, "_request")
    def test_carousel_creates_children_parent_then_publishes(self, request):
        request.side_effect = [
            {"id": "child-1"}, {"id": "child-2"},
            {"id": "carousel-1"}, {"id": "media-1"},
        ]
        with tempfile.NamedTemporaryFile(suffix=".jpg") as first, tempfile.NamedTemporaryFile(suffix=".png") as second:
            result = self.publisher.publish(
                PublisherCredentials("page-token", None, [], None),
                "ig-1",
                PublishRequest(
                    Path(first.name), "Titre", "Légende", PublicationVisibility.PUBLIC,
                    format=PublicationFormat.CAROUSEL,
                    media_paths=(Path(first.name), Path(second.name)),
                    media_urls=("https://cdn.test/1.jpg", "https://cdn.test/2.png"),
                ),
            )
        self.assertEqual(result.external_id, "media-1")
        parent = request.call_args_list[2].kwargs["params"]
        self.assertEqual(parent["media_type"], "CAROUSEL")
        self.assertEqual(parent["children"], "child-1,child-2")

    @patch("api.integrations.instagram.requests.request")
    def test_request_classifies_meta_error_table(self, request):
        cases = [
            (401, {"error": {"message": "unauthorized"}}, SocialErrorCode.AUTHORIZATION, False),
            (403, {"error": {"message": "forbidden"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 190, "message": "token expiré"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 102, "message": "session expirée"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 10, "message": "permission refusée"}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 2500, "error_subcode": 33}}, SocialErrorCode.AUTHORIZATION, False),
            (400, {"error": {"code": 17, "message": "rate limit"}}, SocialErrorCode.TEMPORARY, True),
            (400, {"error": {"code": 613, "message": "rate limit"}}, SocialErrorCode.TEMPORARY, True),
            (429, {"error": {"message": "trop de requêtes"}}, SocialErrorCode.TEMPORARY, True),
            (500, {"error": {"code": 2}}, SocialErrorCode.TEMPORARY, True),
            (400, {"error": {"code": 100, "message": "paramètre invalide"}}, SocialErrorCode.TEMPORARY, False),
        ]
        for status_code, payload, expected_code, expected_retryable in cases:
            with self.subTest(status=status_code, payload=payload):
                request.return_value = _graph_response(status_code, payload)
                with self.assertRaises(SocialPublisherError) as raised:
                    self.publisher._request("GET", "/me", "token")
                self.assertIs(raised.exception.code, expected_code)
                self.assertEqual(raised.exception.retryable, expected_retryable)

    @patch("api.integrations.instagram.requests.request")
    def test_request_returns_payload_without_error(self, request):
        request.return_value = _graph_response(200, {"id": "ig-1"})
        self.assertEqual(
            self.publisher._request("GET", "/me", "token"), {"id": "ig-1"}
        )


if __name__ == "__main__":
    unittest.main()
