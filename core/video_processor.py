"""
Traitement vidéo : conversion optimale pour Shorts YouTube (9:16, 60s max).
Utilise ffmpeg via subprocess ou moviepy selon disponibilité.
"""
import logging
import subprocess
import shutil
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Dimensions Shorts YouTube optimales
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_RATIO = SHORTS_HEIGHT / SHORTS_WIDTH  # 16:9 inversé = 1.777...

# Codecs et formats
TARGET_CODEC = "libx264"
TARGET_AUDIO = "aac"
TARGET_PRESET = "fast"  # "slow" = meilleure qualité mais plus lent


def process_for_short(
    input_path: Path,
    output_path: Path | None = None,
    max_duration: int = config.CLIP_MAX_DURATION_SEC,
    target_duration: int | None = None,
) -> Path:
    """
    Convertit une vidéo au format optimal Shorts YouTube.
    
    Étapes :
    1. Vérifier/extraire la durée
    2. Rogner/padder pour 9:16 (sans déformation)
    3. Limiter la durée si nécessaire
    4. Optimiser codecs pour la taille fichier
    
    Retourne le chemin du fichier traité.
    """
    if output_path is None:
        output_path = config.PROCESSED_DIR / f"{input_path.stem}_short.mp4"
    
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    
    # Vérifier que ffmpeg est installé
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg n'est pas installé. Installez-le : apt install ffmpeg")
    
    # Obtenir les infos de la vidéo source
    probe = _probe_video(input_path)
    duration = float(probe.get("format", {}).get("duration", 0))
    width, height = _get_video_dimensions(probe)
    
    logger.info(
        "Traitement vidéo",
        extra={
            "input": str(input_path),
            "duration": duration,
            "dimensions": f"{width}x{height}",
        },
    )
    
    # Construire la commande ffmpeg
    cmd = _build_ffmpeg_command(
        input_path=input_path,
        output_path=output_path,
        source_width=width,
        source_height=height,
        source_duration=duration,
        max_duration=max_duration,
        target_duration=target_duration,
    )
    
    # Exécuter
    logger.info("Lancement ffmpeg...")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    
    if result.returncode != 0:
        logger.error("ffmpeg stderr: %s", result.stderr[-2000:])  # Dernières lignes
        raise RuntimeError(f"Échec ffmpeg (code {result.returncode}): {result.stderr[:500]}")
    
    # Vérifier le résultat
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Fichier de sortie vide ou inexistant")
    
    logger.info(
        "Traitement terminé",
        extra={"output": str(output_path), "size_mb": output_path.stat().st_size / 1e6},
    )
    
    return output_path


def _probe_video(video_path: Path) -> dict:
    """Extrait les métadonnées via ffprobe."""
    import json
    
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def probe_video_duration(video_path: Path) -> float:
    """Retourne la durée vérifiée d'un fichier vidéo local."""
    duration = float(_probe_video(video_path).get("format", {}).get("duration", 0))
    if duration <= 0:
        raise ValueError("Impossible de déterminer la durée de la vidéo.")
    return duration


def _get_video_dimensions(probe: dict) -> tuple[int, int]:
    """Extrait width/height depuis le flux vidéo."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream.get("width", 0), stream.get("height", 0)
    raise RuntimeError("Aucun flux vidéo trouvé")


def _build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    source_width: int,
    source_height: int,
    source_duration: float,
    max_duration: int,
    target_duration: int | None,
) -> list[str]:
    """Construit la commande ffmpeg complète."""

    # Filtre universel : scale + pad vers 9:16, quel que soit le ratio source
    video_filter = (
        f"scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={SHORTS_WIDTH}:{SHORTS_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1"
    )
    
    # Limiter la durée
    duration_limit = min(source_duration, max_duration)
    if target_duration and target_duration < duration_limit:
        duration_limit = target_duration
    
    cmd = [
        "ffmpeg",
        "-y",  # Écraser sans demander
        "-i", str(input_path),
        "-t", str(duration_limit),  # Durée max
        "-vf", video_filter,
        "-c:v", TARGET_CODEC,
        "-preset", TARGET_PRESET,
        "-crf", "23",  # Qualité (18-28, plus bas = meilleur)
        "-pix_fmt", "yuv420p",  # Compatibilité max
        "-c:a", TARGET_AUDIO,
        "-b:a", "128k",
        "-movflags", "+faststart",  # Streaming-friendly
        str(output_path),
    ]
    
    return cmd


def extract_thumbnail(video_path: Path, time_sec: float = 1.0) -> Path:
    """
    Extrait une vignette depuis la vidéo pour l'upload YouTube.
    """
    output_path = config.PROCESSED_DIR / f"{video_path.stem}_thumb.jpg"
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-ss", str(time_sec),
        "-vframes", "1",
        "-q:v", "2",  # Qualité JPEG (2-31, plus bas = meilleur)
        str(output_path),
    ]
    
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path
