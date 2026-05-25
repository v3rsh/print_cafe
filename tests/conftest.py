"""Test fixtures: fake redis, FastAPI test app, in-memory SQLite session."""

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
# Tests must not inherit the production whitelist from .env; individual tests
# opt-in via monkeypatch.setenv when whitelist behaviour is being exercised.
os.environ.setdefault("WAZZUP_ALLOWED_CHAT_IDS", "")


from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings  # noqa: E402
from app.db import models as _models  # noqa: E402,F401  -- регистрирует таблицы
from app.db.base import Base  # noqa: E402
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


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite + создание таблиц на каждый тест."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


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
