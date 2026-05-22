"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.config import get_settings
from app.db.session import dispose_engine, init_engine
from app.logging_config import configure_logging
from app.wazzup.webhooks import router as wazzup_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    redis: Redis[bytes] = Redis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis
    init_engine()
    logger.info("app_startup", extra={"env": settings.app_env})

    try:
        yield
    finally:
        logger.info("app_shutdown")
        await redis.aclose()  # type: ignore[attr-defined]
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Print Cafe AI Bot",
        version="0.1.0",
        debug=settings.app_debug,
        lifespan=lifespan,
    )
    app.include_router(wazzup_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready(request: Request) -> JSONResponse:
        problems: dict[str, str] = {}
        redis: Redis[bytes] | None = getattr(request.app.state, "redis", None)
        if redis is None:
            problems["redis"] = "not initialised"
        else:
            try:
                await redis.ping()
            except Exception as exc:  # noqa: BLE001
                problems["redis"] = str(exc)

        try:
            from sqlalchemy import text

            from app.db.session import get_engine

            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            problems["database"] = str(exc)

        if problems:
            return JSONResponse(
                {"status": "degraded", "problems": problems},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return JSONResponse({"status": "ready"})

    return app


app = create_app()
