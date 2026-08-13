"""Validation des entrées de vidéos avant accès au stockage."""
import unittest

from pydantic import ValidationError

from api.schemas import VideoCreate


class VideoSchemaTests(unittest.TestCase):
    def test_source_is_required(self):
        with self.assertRaises(ValidationError):
            VideoCreate(title="Sans source")

    def test_http_source_is_accepted(self):
        payload = VideoCreate(source_url="https://example.com/video.mp4")
        self.assertEqual(str(payload.source_url), "https://example.com/video.mp4")

    def test_absolute_storage_key_is_rejected(self):
        with self.assertRaises(ValidationError):
            VideoCreate(storage_key="/etc/passwd")

    def test_parent_storage_segment_is_rejected(self):
        with self.assertRaises(ValidationError):
            VideoCreate(storage_key="workspaces/../secret.mp4")
