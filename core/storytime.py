"""
Génération du texte narratif "storytime" via l'API Grok (xAI),
calibré pour correspondre à la durée du clip.
L'API xAI est compatible OpenAI : on utilise le SDK openai
avec un base_url différent.
"""
from openai import OpenAI

import config

_client = OpenAI(
    api_key=config.XAI_API_KEY,
    base_url="https://api.x.ai/v1",
)

# ~150 mots/min de lecture naturelle pour du storytime (rythme oral, pas de lecture rapide)
WORDS_PER_MINUTE = 150


def generate_story(theme_hint: str, target_duration_sec: float) -> str:
    """
    Génère un texte narratif dont la durée de lecture correspond
    approximativement à target_duration_sec.
    """
    target_words = int((target_duration_sec / 60) * WORDS_PER_MINUTE)

    prompt = (
        f"Écris une histoire courte et captivante en français, style storytime, "
        f"sur le thème : {theme_hint}. "
        f"Longueur cible : environ {target_words} mots (respecte cette longueur, "
        f"ni trop court ni trop long). "
        f"Ton engageant, rythme qui accroche dès la première phrase, "
        f"pas d'introduction du type 'voici une histoire', va directement au récit."
    )

    response = _client.chat.completions.create(
        model=config.XAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
    )

    return response.choices[0].message.content.strip()