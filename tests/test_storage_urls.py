"""Tests des URLs temporaires Cloudflare R2."""
import unittest
from unittest.mock import Mock, patch

from core.storage_r2 import create_presigned_download_url


class SignedStorageURLTests(unittest.TestCase):
    @patch("core.storage_r2._client")
    @patch("core.storage_r2.config.R2_ENDPOINT_URL", "https://account.r2.cloudflarestorage.com")
    @patch("core.storage_r2.config.R2_SECRET_ACCESS_KEY", "secret")
    @patch("core.storage_r2.config.R2_ACCESS_KEY_ID", "access")
    @patch("core.storage_r2.config.R2_BUCKET_NAME", "test-bucket")
    def test_private_object_gets_short_lived_url(self, client_factory):
        client = Mock()
        client.generate_presigned_url.return_value = "https://signed.example/video.mp4?signature=x"
        client_factory.return_value = client
        url = create_presigned_download_url("workspaces/ws/rendered/video.mp4", 900)
        self.assertIn("signature=x", url)
        client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "test-bucket",
                "Key": "workspaces/ws/rendered/video.mp4",
            },
            ExpiresIn=900,
        )

    def test_expiration_is_bounded(self):
        with self.assertRaises(ValueError):
            create_presigned_download_url("workspaces/ws/video.mp4", 59)
        with self.assertRaises(ValueError):
            create_presigned_download_url("workspaces/ws/video.mp4", 3601)


if __name__ == "__main__":
    unittest.main()
