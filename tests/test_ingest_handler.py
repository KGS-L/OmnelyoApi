"""Tests de sécurité du handler d'ingestion distant."""
import socket
import unittest
from unittest.mock import patch

from api.models import JobType
from workers.handlers.ingest import validate_public_source_url
from workers.registry import registry


def address_info(address: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


class IngestURLValidationTests(unittest.TestCase):
    def test_ingest_handler_is_registered(self):
        self.assertIsNotNone(registry.get(JobType.INGEST))

    @patch("workers.handlers.ingest.socket.getaddrinfo")
    def test_public_address_is_accepted(self, getaddrinfo):
        getaddrinfo.return_value = address_info("8.8.8.8")
        validate_public_source_url("https://videos.example.com/source.mp4")

    @patch("workers.handlers.ingest.socket.getaddrinfo")
    def test_loopback_address_is_rejected(self, getaddrinfo):
        getaddrinfo.return_value = address_info("127.0.0.1")
        with self.assertRaises(ValueError):
            validate_public_source_url("https://localhost/video.mp4")

    @patch("workers.handlers.ingest.socket.getaddrinfo")
    def test_private_address_is_rejected(self, getaddrinfo):
        getaddrinfo.return_value = address_info("10.0.0.5")
        with self.assertRaises(ValueError):
            validate_public_source_url("https://internal.example.com/video.mp4")

    def test_non_http_scheme_is_rejected_without_dns(self):
        with self.assertRaises(ValueError):
            validate_public_source_url("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
