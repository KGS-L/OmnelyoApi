"""Tests du stockage et de l'enregistrement du handler PROCESS."""
import tempfile
import unittest
from pathlib import Path

import config
from api.models import JobType
from core.storage_r2 import download_from_r2, upload_to_r2
from workers.registry import registry


class ProcessHandlerTests(unittest.TestCase):
    def test_process_handler_is_registered(self):
        self.assertIsNotNone(registry.get(JobType.PROCESS))

    def test_local_storage_roundtrip(self):
        old_processed_dir = config.PROCESSED_DIR
        old_access = config.R2_ACCESS_KEY_ID
        old_secret = config.R2_SECRET_ACCESS_KEY
        old_endpoint = config.R2_ENDPOINT_URL
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.mp4"
            source.write_bytes(b"video-content")
            try:
                config.PROCESSED_DIR = root / "objects"
                config.R2_ACCESS_KEY_ID = ""
                config.R2_SECRET_ACCESS_KEY = ""
                config.R2_ENDPOINT_URL = ""
                key = "workspaces/ws/jobs/job/source/input.mp4"
                with self.assertLogs("core.storage_r2", level="WARNING"):
                    upload_to_r2(source, key)
                destination = root / "download" / "input.mp4"
                download_from_r2(key, destination)
                self.assertEqual(destination.read_bytes(), b"video-content")
            finally:
                config.PROCESSED_DIR = old_processed_dir
                config.R2_ACCESS_KEY_ID = old_access
                config.R2_SECRET_ACCESS_KEY = old_secret
                config.R2_ENDPOINT_URL = old_endpoint

    def test_storage_parent_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video-content")
            with self.assertRaises(ValueError):
                upload_to_r2(source, "workspaces/../secret.mp4")


if __name__ == "__main__":
    unittest.main()
