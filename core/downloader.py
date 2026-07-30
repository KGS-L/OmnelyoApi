"""
Téléchargement de la vidéo source depuis un lien YouTube (yt-dlp).
"""
from pathlib import Path


def download_video(url: str, output_dir: Path) -> Path:
    """
    Télécharge la vidéo depuis `url` vers `output_dir`.
    Retourne le chemin local du fichier téléchargé.
    """
    raise NotImplementedError
