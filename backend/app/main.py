import logging
import time
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.limiter import limiter

settings = get_settings()
logger = logging.getLogger(__name__)

logging.basicConfig(level=settings.LOG_LEVEL.upper())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("IrrigAI backend starting up...")
    yield
    logger.info("IrrigAI backend shutting down...")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="IrrigAI API",
        version="0.1.0",
        description="AI-powered irrigation planning and recommendation system",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Request ID + request logging — pure ASGI middleware (avoids BaseHTTPMiddleware
    # event-loop conflicts with asyncpg when running under pytest)
    from starlette.types import ASGIApp, Receive, Scope, Send

    class RequestMiddleware:
        def __init__(self, inner: ASGIApp) -> None:
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.inner(scope, receive, send)
                return

            headers = dict(scope.get("headers", []))
            request_id = headers.get(b"x-request-id", str(uuid.uuid4()).encode()).decode()
            start = time.perf_counter()

            async def send_with_header(message):
                if message["type"] == "http.response.start":
                    new_headers = list(message.get("headers", []))
                    new_headers.append((b"x-request-id", request_id.encode()))
                    message = {**message, "headers": new_headers}
                    duration_ms = round((time.perf_counter() - start) * 1000, 1)
                    method = scope.get("method", "?")
                    path = scope.get("path", "?")
                    logger.info(
                        "%s %s → %s  (%.0fms) [%s]",
                        method, path, message["status"], duration_ms, request_id,
                    )
                await send(message)

            await self.inner(scope, receive, send_with_header)

    app.add_middleware(RequestMiddleware)

    # Health check
    @app.get("/health", tags=["ops"])
    async def health():
        checks: dict[str, str] = {}
        meta: dict = {"version": "0.1.0"}

        # DB check
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as exc:
            logger.error("DB health check failed: %s", exc)
            checks["db"] = "error"

        # Redis check
        try:
            r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.error("Redis health check failed: %s", exc)
            checks["redis"] = "error"

        # Last data ingestion
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
        status_code = 200 if all_ok else 503

        return JSONResponse(
            status_code=status_code,
            content={"status": "ok" if all_ok else "degraded", "checks": checks, **meta},
        )

    # API v1
    from app.api.v1 import router as v1_router

    app.include_router(v1_router, prefix="/api/v1")

    # Validation error → consistent format
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "error_code": "validation_error"},
        )

    # Generic exception handler
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_code": "internal_error"},
        )

    return app


app = create_app()
