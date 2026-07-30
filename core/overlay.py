"""
Génération de la card visuelle (style commentaire) et incrustation
en haut/centre de la vidéo pendant 8 secondes.
"""
from pathlib import Path


def render_comment_card(text: str, output_image_path: Path) -> Path:
    """
    Génère l'image de la card (via Pillow ou rendu HTML/Playwright).
    Retourne le chemin de l'image générée.
    """
    raise NotImplementedError


def overlay_card_on_video(
    video_path: Path,
    card_image_path: Path,
    duration_sec: int,
    output_path: Path,
) -> Path:
    """
    Incruste la card en haut/centre de `video_path` pendant `duration_sec`.
    Retourne le chemin de la vidéo finale.
    """
    raise NotImplementedError
