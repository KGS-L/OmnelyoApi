"""
Découpage effectif des clips (ffmpeg) à partir des plages calculées,
avec suppression de l'audio original.
"""
from pathlib import Path


def cut_clip(
    source_path: Path,
    start_sec: float,
    end_sec: float,
    output_path: Path,
    remove_audio: bool = True,
) -> Path:
    """
    Découpe un segment [start_sec, end_sec] de `source_path` vers `output_path`.
    Retourne le chemin du clip généré.
    """
    raise NotImplementedError
