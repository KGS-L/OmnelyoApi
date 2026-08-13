"""Génération de la voix off du storytime avec OpenAI TTS."""
import logging
from pathlib import Path

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

def generate_tts(text: str, output_path: Path) -> Path:
    """
    Génère l'audio de la voix off pour `text` et l'enregistre dans `output_path`.
    Retourne le chemin du fichier audio généré.
    """
    if config.TTS_PROVIDER != "openai":
        raise ValueError("Seul TTS_PROVIDER=openai est actuellement pris en charge.")
    if not config.OPENAI_API_KEY:
        logger.error("Clé API OpenAI manquante pour le TTS.")
        raise ValueError(
            "OPENAI_API_KEY n'est pas configurée pour la génération de voix off."
        )
    if not text.strip():
        raise ValueError("Le texte TTS ne peut pas être vide.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info("Appel OpenAI TTS pour générer la voix off (%s caractères)...", len(text))
    
    try:
        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=60.0, max_retries=2)
        with client.audio.speech.with_streaming_response.create(
            model=config.OPENAI_TTS_MODEL,
            voice=config.OPENAI_TTS_VOICE,
            input=text,
            instructions=config.OPENAI_TTS_INSTRUCTIONS,
            response_format="mp3",
        ) as response:
            response.stream_to_file(output_path)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("OpenAI TTS a produit un fichier audio vide.")
        logger.info("Fichier voix off enregistré avec succès : %s", output_path)
        return output_path
    except Exception as e:
        logger.exception("Échec lors de la génération de la voix off via OpenAI")
        raise RuntimeError(f"Échec de la génération TTS : {e}") from e
