"""Réception bornée et détection du type réel des vidéos envoyées à l'API."""
from pathlib import Path

from fastapi import UploadFile

CHUNK_SIZE = 1024 * 1024
VIDEO_SIGNATURES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}
IMAGE_SIGNATURES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def detect_video_type(header: bytes) -> tuple[str, str]:
    if len(header) >= 12 and header[4:8] == b"ftyp":
        major_brand = header[8:12]
        mime = "video/quicktime" if major_brand == b"qt  " else "video/mp4"
        return mime, VIDEO_SIGNATURES[mime]
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm", VIDEO_SIGNATURES["video/webm"]
    raise ValueError("Le contenu du fichier n'est pas une vidéo MP4, MOV ou WebM reconnue.")


def detect_image_type(header: bytes) -> tuple[str, str]:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", IMAGE_SIGNATURES["image/png"]
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", IMAGE_SIGNATURES["image/jpeg"]
    raise ValueError("Le contenu du fichier n'est pas une image JPEG ou PNG reconnue.")


def image_dimensions(path: Path, mime_type: str) -> tuple[int, int]:
    """Lit les dimensions sans décoder l'image entière en mémoire."""
    with path.open("rb") as image:
        if mime_type == "image/png":
            header = image.read(24)
            if len(header) != 24 or header[12:16] != b"IHDR":
                raise ValueError("L'en-tête PNG est invalide.")
            width = int.from_bytes(header[16:20], "big")
            height = int.from_bytes(header[20:24], "big")
        else:
            image.read(2)
            while True:
                marker_start = image.read(1)
                if not marker_start:
                    raise ValueError("Les dimensions JPEG sont introuvables.")
                if marker_start != b"\xff":
                    continue
                marker = image.read(1)
                while marker == b"\xff":
                    marker = image.read(1)
                if marker in {bytes([value]) for value in range(0xC0, 0xD4)} - {b"\xc4", b"\xc8", b"\xcc"}:
                    length = int.from_bytes(image.read(2), "big")
                    segment = image.read(length - 2)
                    if len(segment) < 5:
                        raise ValueError("L'en-tête JPEG est tronqué.")
                    height = int.from_bytes(segment[1:3], "big")
                    width = int.from_bytes(segment[3:5], "big")
                    break
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                length_bytes = image.read(2)
                if len(length_bytes) != 2:
                    raise ValueError("L'en-tête JPEG est tronqué.")
                image.seek(int.from_bytes(length_bytes, "big") - 2, 1)
    if width <= 0 or height <= 0 or width * height > 100_000_000:
        raise ValueError("Les dimensions de l'image sont invalides ou trop grandes.")
    return width, height


async def stream_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    if max_bytes <= 0:
        raise ValueError("La limite d'upload doit être positive.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    header = bytearray()
    try:
        with destination.open("xb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(
                        f"La vidéo dépasse la limite de {max_bytes} octets."
                    )
                if len(header) < 32:
                    header.extend(chunk[: 32 - len(header)])
                output.write(chunk)
        if total == 0:
            raise ValueError("La vidéo envoyée est vide.")
        detect_video_type(bytes(header))
        return total
    except Exception:
        destination.unlink(missing_ok=True)
        raise


async def stream_image_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    if max_bytes <= 0:
        raise ValueError("La limite d'upload doit être positive.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    header = bytearray()
    try:
        with destination.open("xb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"L'image dépasse la limite de {max_bytes} octets.")
                if len(header) < 32:
                    header.extend(chunk[: 32 - len(header)])
                output.write(chunk)
        if total == 0:
            raise ValueError("L'image envoyée est vide.")
        detect_image_type(bytes(header))
        return total
    except Exception:
        destination.unlink(missing_ok=True)
        raise
