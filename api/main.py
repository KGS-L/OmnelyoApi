"""Application FastAPI du SaaS."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.routes import (
    auth,
    channels,
    jobs,
    publications,
    telegram_integration,
    users,
    videos,
    workspaces,
)

settings = get_settings()
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
app.include_router(telegram_integration.router, prefix="/v1")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
