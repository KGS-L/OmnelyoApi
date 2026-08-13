"""Corrélation HTTP, logs JSON, rate limiting Redis et audit des mutations."""
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from redis import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from api.database import SessionLocal
from api.models import AuditEvent

logger = logging.getLogger(__name__)
request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_structured_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            logger.info(
                "%s %s -> %s en %sms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            if request.method in MUTATING_METHODS and request.url.path.startswith("/v1/"):
                await run_in_threadpool(_record_audit, request, response.status_code)
            return response
        finally:
            request_id_context.reset(token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_url: str, limit: int, enabled: bool = True):
        super().__init__(app)
        self.redis = Redis.from_url(
            redis_url, socket_connect_timeout=0.2, socket_timeout=0.2
        )
        self.limit = max(1, limit)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        if not self.enabled or request.url.path in {"/health", "/docs", "/openapi.json"}:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        minute = int(time.time() // 60)
        key = f"rate:api:{client}:{minute}"
        try:
            allowed, remaining = await run_in_threadpool(self._consume, key)
        except RedisError:
            logger.warning("Rate limiting Redis indisponible ; requête autorisée.")
            return await call_next(request)
        if not allowed:
            return JSONResponse(
                {"detail": "Trop de requêtes. Réessaie dans moins d'une minute."},
                status_code=429,
                headers={"Retry-After": "60", "X-RateLimit-Remaining": "0"},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    def _consume(self, key: str) -> tuple[bool, int]:
        pipeline = self.redis.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, 70)
        count, _ = pipeline.execute()
        return count <= self.limit, max(0, self.limit - count)


def _record_audit(request: Request, response_status: int) -> None:
    try:
        with SessionLocal() as db:
            db.add(
                AuditEvent(
                    workspace_id=getattr(request.state, "workspace_id", None),
                    actor_user_id=getattr(request.state, "actor_user_id", None),
                    action=request.method.lower(),
                    resource_path=request.url.path,
                    request_id=request.state.request_id,
                    response_status=response_status,
                    details={"query": sorted(request.query_params.keys())},
                )
            )
            db.commit()
    except Exception:
        logger.exception("Impossible d'enregistrer l'événement d'audit.")
