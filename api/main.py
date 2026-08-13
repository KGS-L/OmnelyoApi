"""Application FastAPI du SaaS."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.integrations.social import social_publishers
from api.integrations.youtube import YouTubePublisher
from api.integrations.tiktok import TikTokPublisher
from api.integrations.facebook import FacebookPublisher
from api.integrations.instagram import InstagramPublisher
from api.models import ChannelPlatform
from api.routes import (
    auth,
    channels,
    jobs,
    publications,
    social_integrations,
    telegram_integration,
    users,
    videos,
    workspaces,
)

settings = get_settings()
if not social_publishers.has(ChannelPlatform.YOUTUBE):
    social_publishers.register(YouTubePublisher(settings.youtube_client_secrets_file))
if not social_publishers.has(ChannelPlatform.TIKTOK):
    social_publishers.register(TikTokPublisher(
        settings.tiktok_client_key, settings.tiktok_client_secret, settings.tiktok_sandbox_mode
    ))
if not social_publishers.has(ChannelPlatform.FACEBOOK):
    social_publishers.register(FacebookPublisher(
        settings.meta_app_id, settings.meta_app_secret, settings.meta_graph_api_version
    ))
if not social_publishers.has(ChannelPlatform.INSTAGRAM):
    social_publishers.register(InstagramPublisher(
        settings.meta_app_id, settings.meta_app_secret, settings.meta_graph_api_version
    ))
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router, prefix="/v1")
app.include_router(users.router, prefix="/v1")
app.include_router(workspaces.router, prefix="/v1")
app.include_router(channels.router, prefix="/v1")
app.include_router(videos.router, prefix="/v1")
app.include_router(jobs.router, prefix="/v1")
app.include_router(publications.router, prefix="/v1")
app.include_router(social_integrations.workspace_router, prefix="/v1")
app.include_router(social_integrations.callback_router, prefix="/v1")
app.include_router(telegram_integration.router, prefix="/v1")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
