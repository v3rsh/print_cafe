"""Test fixtures: fake redis, FastAPI test app without DB / Yandex calls."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("APP_DEBUG", "true")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("WAZZUP_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("WAZZUP_API_KEY", "test-wazzup-key")
os.environ.setdefault("YANDEX_API_KEY", "test-yandex-key")
os.environ.setdefault("YANDEX_FOLDER_ID", "test-folder")
os.environ.setdefault("YANDEX_MODEL", "gpt://test-folder/yandexgpt/rc")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


from app.config import get_settings  # noqa: E402
from app.wazzup.webhooks import router as wazzup_router  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[Any]:
    redis = fakeredis.FakeRedis(decode_responses=False)
    try:
        yield redis
    finally:
        await redis.aclose()


def _build_app(redis: Any) -> FastAPI:
    app = FastAPI()
    app.state.redis = redis
    app.include_router(wazzup_router)
    return app


@pytest_asyncio.fixture
async def webhook_client(fake_redis: Any) -> AsyncIterator[AsyncClient]:
    app = _build_app(fake_redis)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
