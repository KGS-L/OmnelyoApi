"""Tests de réception bornée et de détection réelle des vidéos."""
import tempfile
import unittest
from pathlib import Path

from api.media_upload import (
    detect_image_type,
    detect_video_type,
    image_dimensions,
    stream_upload,
)


class AsyncUpload:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class MediaUploadTests(unittest.IsolatedAsyncioTestCase):
    def test_png_type_and_dimensions_are_detected(self):
        header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1080).to_bytes(4, "big") + (1350).to_bytes(4, "big")
        self.assertEqual(detect_image_type(header), ("image/png", ".png"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            path.write_bytes(header)
            self.assertEqual(image_dimensions(path, "image/png"), (1080, 1350))

    def test_unknown_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JPEG ou PNG"):
            detect_image_type(b"GIF89a")

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
