"""
Génération de la voix off (TTS) à partir du texte storytime.
Utilise ElevenLabs pour une synthèse vocale réaliste en français.
"""
import logging
import requests
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# ID de voix par défaut (ex. Rachel: 21m00Tcm4TlvDq8ikWAM, Antoni: ErXwobaYiN019vkySvjV)
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"


def generate_tts(text: str, output_path: Path) -> Path:
    """
    Génère l'audio de la voix off pour `text` et l'enregistre dans `output_path`.
    Retourne le chemin du fichier audio généré.
    """
    if not config.ELEVENLABS_API_KEY:
        logger.error("Clé API ElevenLabs manquante dans la configuration.")
        raise ValueError(
            "La variable d'environnement ELEVENLABS_API_KEY n'est pas configurée. "
            "Veuillez l'ajouter au fichier .env pour activer la génération de voix off."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{DEFAULT_VOICE_ID}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": config.ELEVENLABS_API_KEY
    }
    
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",  # Indispensable pour le français
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    logger.info(f"Appel ElevenLabs TTS pour générer la voix off ({len(text)} caractères)...")
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Erreur ElevenLabs API (Code {response.status_code}): {response.text}")
            raise RuntimeError(f"L'API ElevenLabs a répondu avec le code {response.status_code} : {response.text}")
            
        output_path.write_bytes(response.content)
        logger.info(f"Fichier voix off enregistré avec succès : {output_path}")
        return output_path
        
    except Exception as e:
        logger.exception("Échec lors de la génération de la voix off via ElevenLabs")
        raise RuntimeError(f"Échec de la génération TTS : {e}") from e
