"""Câblage unique des adaptateurs sociaux, partagé par l'API et les workers."""
from api.config import APISettings
from api.integrations.facebook import FacebookPublisher
from api.integrations.instagram import InstagramPublisher
from api.integrations.social import SocialPublisherRegistry, social_publishers
from api.integrations.tiktok import TikTokPublisher
from api.integrations.youtube import YouTubePublisher
from api.models import ChannelPlatform


def register_default_publishers(
    settings: APISettings,
    registry: SocialPublisherRegistry = social_publishers,
) -> None:
    """Enregistre une seule fois les adaptateurs des plateformes supportées."""
    if not registry.has(ChannelPlatform.YOUTUBE):
        registry.register(YouTubePublisher(settings.youtube_client_secrets_file))
    if not registry.has(ChannelPlatform.TIKTOK):
        registry.register(TikTokPublisher(
            settings.tiktok_client_key, settings.tiktok_client_secret, settings.tiktok_sandbox_mode,
        ))
    if not registry.has(ChannelPlatform.FACEBOOK):
        registry.register(FacebookPublisher(
            settings.meta_app_id, settings.meta_app_secret, settings.meta_graph_api_version,
        ))
    if not registry.has(ChannelPlatform.INSTAGRAM):
        registry.register(InstagramPublisher(
            settings.meta_app_id, settings.meta_app_secret, settings.meta_graph_api_version,
        ))
