"""Réception bornée et détection du type réel des vidéos envoyées à l'API."""
from pathlib import Path

from fastapi import UploadFile

CHUNK_SIZE = 1024 * 1024
VIDEO_SIGNATURES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


def detect_video_type(header: bytes) -> tuple[str, str]:
    if len(header) >= 12 and header[4:8] == b"ftyp":
        major_brand = header[8:12]
        mime = "video/quicktime" if major_brand == b"qt  " else "video/mp4"
        return mime, VIDEO_SIGNATURES[mime]
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm", VIDEO_SIGNATURES["video/webm"]
    raise ValueError("Le contenu du fichier n'est pas une vidéo MP4, MOV ou WebM reconnue.")


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
