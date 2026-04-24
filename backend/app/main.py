import time
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.limiter import limiter
from app.logging_config import request_id_var, setup_logging

settings = get_settings()
setup_logging(settings.LOG_LEVEL)

import logging  # noqa: E402 — after setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("IrrigAI backend starting up")
    yield
    logger.info("IrrigAI backend shutting down")
    await engine.dispose()


def create_app() -> FastAPI:
    # ── Sentry (opt-in: only initialised when SENTRY_DSN is set) ─────────────
    if settings.SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.05,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            send_default_pii=False,
        )
        logger.info("Sentry initialised (env=%s)", settings.SENTRY_ENVIRONMENT)

    app = FastAPI(
        title="IrrigAI API",
        version="0.1.0",
        description="AI-powered irrigation planning and recommendation system",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── Request middleware: ID, logging, metrics, security headers ────────────
    # Pure ASGI — avoids BaseHTTPMiddleware asyncpg event-loop conflicts.
    from starlette.types import ASGIApp, Receive, Scope, Send

    from app.metrics import http_request_duration_seconds, http_requests_total

    _SECURITY_HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"x-xss-protection", b"1; mode=block"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]

    class RequestMiddleware:
        def __init__(self, inner: ASGIApp) -> None:
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.inner(scope, receive, send)
                return

            headers = dict(scope.get("headers", []))
            request_id = (
                headers.get(b"x-request-id", b"").decode()
                or str(uuid.uuid4())
            )
            token = request_id_var.set(request_id)
            start = time.perf_counter()
            method = scope.get("method", "?")
            path = scope.get("path", "?")

            async def send_with_headers(message):
                if message["type"] == "http.response.start":
                    status = message["status"]
                    duration = time.perf_counter() - start
                    new_headers = list(message.get("headers", []))
                    new_headers.append((b"x-request-id", request_id.encode()))
                    new_headers.extend(_SECURITY_HEADERS)
                    message = {**message, "headers": new_headers}
                    logger.info(
                        "http_request",
                        extra={
                            "method": method,
                            "path": path,
                            "status": status,
                            "duration_ms": round(duration * 1000, 1),
                        },
                    )
                    http_requests_total.labels(method, path, str(status)).inc()
                    http_request_duration_seconds.labels(method, path).observe(duration)
                await send(message)

            try:
                await self.inner(scope, receive, send_with_headers)
            finally:
                request_id_var.reset(token)

    app.add_middleware(RequestMiddleware)

    # ── Prometheus /metrics endpoint ──────────────────────────────────────────
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    @app.get("/metrics", include_in_schema=False, tags=["ops"])
    async def metrics():
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    # ── Health ────────────────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"])
    async def health():
        checks: dict[str, str] = {}
        meta: dict = {"version": "0.1.0"}

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as exc:
            logger.error("DB health check failed: %s", exc)
            checks["db"] = "error"

        try:
            r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.error("Redis health check failed: %s", exc)
            checks["redis"] = "error"

        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT MAX(timestamp) FROM probe_reading")
                )
                ts = result.scalar()
                meta["last_ingestion_at"] = ts.isoformat() if ts else None
        except Exception:
            meta["last_ingestion_at"] = None

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={"status": "ok" if all_ok else "degraded", "checks": checks, **meta},
        )

    # ── API v1 ────────────────────────────────────────────────────────────────
    from app.api.v1 import router as v1_router

    app.include_router(v1_router, prefix="/api/v1")

    # ── Exception handlers ────────────────────────────────────────────────────
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "error_code": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        if settings.SENTRY_DSN:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_code": "internal_error"},
        )

    return app


# Needed for the /metrics import
from starlette.responses import Response  # noqa: E402

app = create_app()
