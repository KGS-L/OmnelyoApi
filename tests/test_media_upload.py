"""Tests de réception bornée et de détection réelle des vidéos."""
import tempfile
import unittest
from pathlib import Path

from api.media_upload import detect_video_type, stream_upload


class AsyncUpload:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class MediaUploadTests(unittest.IsolatedAsyncioTestCase):
    def test_detects_mp4_from_content_not_filename(self):
        mime_type, suffix = detect_video_type(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20)
        self.assertEqual((mime_type, suffix), ("video/mp4", ".mp4"))

    def test_detects_quicktime_brand(self):
        mime_type, suffix = detect_video_type(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 20)
        self.assertEqual((mime_type, suffix), ("video/quicktime", ".mov"))

    def test_rejects_extension_disguised_as_video(self):
        with self.assertRaisesRegex(ValueError, "contenu"):
            detect_video_type(b"not really a video")

    async def test_streams_upload_to_disk(self):
        payload = b"\x00\x00\x00\x18ftypisom" + b"x" * 128
        upload = AsyncUpload(payload)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "upload.part"
            size = await stream_upload(upload, destination, 1024)
            self.assertEqual(size, len(payload))
            self.assertEqual(destination.read_bytes(), payload)

    async def test_oversized_upload_is_removed(self):
        payload = b"\x00\x00\x00\x18ftypisom" + b"x" * 128
        upload = AsyncUpload(payload)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "upload.part"
            with self.assertRaisesRegex(ValueError, "limite"):
                await stream_upload(upload, destination, 16)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
