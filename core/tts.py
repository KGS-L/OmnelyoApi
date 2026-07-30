"""
Génération de la voix off (TTS) à partir du texte storytime.
"""
from pathlib import Path


def generate_tts(text: str, output_path: Path) -> Path:
    """
    Génère l'audio de la voix off pour `text` et l'enregistre dans `output_path`.
    Retourne le chemin du fichier audio généré.
    """
    raise NotImplementedError
