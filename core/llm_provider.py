"""Configuration et création des clients LLM interchangeables."""
from dataclasses import dataclass

import config


@dataclass(frozen=True)
class LLMSettings:
    name: str
    api_key: str
    model: str
    base_url: str | None = None


def get_llm_settings(provider: str | None = None) -> LLMSettings:
    """Retourne la configuration du fournisseur actif, sans exposer sa clé."""
    provider_name = (provider or config.LLM_PROVIDER).strip().lower()
    providers = {
        "openai": LLMSettings("openai", config.OPENAI_API_KEY, config.OPENAI_MODEL),
        "gemini": LLMSettings(
            "gemini",
            config.GEMINI_API_KEY,
            config.GEMINI_MODEL,
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        "groq": LLMSettings(
            "groq", config.GROQ_API_KEY, config.GROQ_MODEL, "https://api.groq.com/openai/v1"
        ),
        "xai": LLMSettings(
            "xai", config.XAI_API_KEY, config.XAI_MODEL, "https://api.x.ai/v1"
        ),
        "grok": LLMSettings(
            "xai", config.XAI_API_KEY, config.XAI_MODEL, "https://api.x.ai/v1"
        ),
        "mistral": LLMSettings(
            "mistral", config.MISTRAL_API_KEY, config.MISTRAL_MODEL, "https://api.mistral.ai/v1"
        ),
        "kimi": LLMSettings(
            "kimi", config.KIMI_API_KEY, config.KIMI_MODEL, config.KIMI_BASE_URL
        ),
    }

    if provider_name not in providers:
        supported = ", ".join(sorted(providers))
        raise ValueError(f"LLM_PROVIDER '{provider_name}' inconnu. Valeurs acceptées : {supported}")

    settings = providers[provider_name]
    if not settings.api_key:
        raise ValueError(
            f"La clé API du fournisseur LLM '{settings.name}' n'est pas configurée."
        )
    if not settings.model:
        raise ValueError(f"Le modèle du fournisseur LLM '{settings.name}' n'est pas configuré.")
    return settings


def create_llm_client(settings: LLMSettings):
    """Crée un client compatible OpenAI pour le fournisseur demandé."""
    from openai import OpenAI

    kwargs = {"api_key": settings.api_key, "timeout": 60.0, "max_retries": 2}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return OpenAI(**kwargs)
