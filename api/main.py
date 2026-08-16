"""Application FastAPI du SaaS."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.integrations.default_publishers import register_default_publishers
from api.observability import RateLimitMiddleware, RequestContextMiddleware, configure_structured_logging
from api.routes import (
    audit,
    auth,
    channels,
    jobs,
    media_assets,
    publications,
    social_integrations,
    telegram_integration,
    users,
    videos,
    workspaces,
)

settings = get_settings()
configure_structured_logging()
register_default_publishers(settings)
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    RateLimitMiddleware,
    redis_url=settings.redis_url,
    limit=settings.api_rate_limit_per_minute,
    enabled=settings.api_rate_limit_enabled,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router, prefix="/v1")
app.include_router(audit.router, prefix="/v1")
app.include_router(users.router, prefix="/v1")
app.include_router(workspaces.router, prefix="/v1")
app.include_router(channels.router, prefix="/v1")
app.include_router(videos.router, prefix="/v1")
app.include_router(jobs.router, prefix="/v1")
app.include_router(media_assets.router, prefix="/v1")
app.include_router(publications.router, prefix="/v1")
app.include_router(social_integrations.workspace_router, prefix="/v1")
app.include_router(social_integrations.callback_router, prefix="/v1")
app.include_router(telegram_integration.router, prefix="/v1")

# Billing routes are always mounted; each endpoint enforces billing_enabled at runtime
from api.routes import billing as billing_routes  # local import to avoid import cycles at startup  # noqa: E402
app.include_router(billing_routes.router, prefix="/v1")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
