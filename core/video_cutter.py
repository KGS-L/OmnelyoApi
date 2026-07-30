"""
Découpage effectif des clips (ffmpeg) à partir des plages calculées,
avec suppression de l'audio original.
"""
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Utilisation du réencodage libx264 pour forcer le découpage exact à l'image près
    # (indispensable si start_sec ne commence pas sur un Keyframe I-Frame)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", str(source_path),
    ]
    
    if remove_audio:
        cmd.append("-an")
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ])
    
    logger.info(
        f"Découpage du segment [{start_sec}s - {end_sec}s] de {source_path.name} "
        f"vers {output_path.name} (audio_supprimé={remove_audio})"
    )
    
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    
    if result.returncode != 0:
        logger.error(f"Ffmpeg error logs: {result.stderr}")
        raise RuntimeError(f"Échec du découpage ffmpeg (code {result.returncode}) : {result.stderr[:400]}")
        
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise FileNotFoundError(f"Le fichier découpé est vide ou introuvable : {output_path}")
        
    return output_path
