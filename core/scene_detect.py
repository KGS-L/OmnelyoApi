"""
Détection des scènes (PySceneDetect) + fusion pour respecter
CLIP_MIN_DURATION_SEC / CLIP_MAX_DURATION_SEC (voir config.py).
"""
from pathlib import Path


def detect_scenes(video_path: Path) -> list[tuple[float, float]]:
    """
    Retourne la liste brute des scènes détectées : [(start_sec, end_sec), ...]
    """
    raise NotImplementedError


def merge_scenes_to_clip_ranges(
    scenes: list[tuple[float, float]],
    min_duration: int,
    max_duration: int,
) -> list[tuple[float, float]]:
    """
    Fusionne/découpe les scènes brutes pour obtenir des plages
    respectant min_duration <= durée <= max_duration.
    """
    raise NotImplementedError
