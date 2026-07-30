"""
Génération du texte narratif "storytime" via API LLM,
calibré pour correspondre à la durée du clip.
"""


def generate_story(theme_hint: str, target_duration_sec: float) -> str:
    """
    Génère un texte narratif dont la durée de lecture (~150 mots/min en moyenne)
    correspond approximativement à target_duration_sec.
    """
    raise NotImplementedError
