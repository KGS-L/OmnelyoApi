"""Génération du storytime avec le fournisseur LLM configuré."""
from core.llm_provider import create_llm_client, get_llm_settings

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

    settings = get_llm_settings()
    client = create_llm_client(settings)
    response = client.chat.completions.create(
        model=settings.model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=1,
        max_tokens=2048,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(f"Le fournisseur LLM '{settings.name}' a retourné une réponse vide.")
    return content.strip()
