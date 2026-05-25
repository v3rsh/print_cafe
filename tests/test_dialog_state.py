"""Tests for Redis-backed dialog state."""

from __future__ import annotations

from typing import Any

import pytest

from app.dialog.state import DialogMessage, DialogStateStore


@pytest.mark.asyncio
async def test_append_and_read(fake_redis: Any) -> None:
    store = DialogStateStore(fake_redis, window=20, ttl_seconds=60)
    await store.append_message("c1", DialogMessage(role="user", content="hi"))
    await store.append_message("c1", DialogMessage(role="assistant", content="hello"))

    history = await store.get_history("c1")
    assert [(m.role, m.content) for m in history] == [
        ("user", "hi"),
        ("assistant", "hello"),
    ]


@pytest.mark.asyncio
async def test_window_trimming(fake_redis: Any) -> None:
    store = DialogStateStore(fake_redis, window=3, ttl_seconds=60)
    for i in range(5):
        await store.append_message("c2", DialogMessage(role="user", content=f"m{i}"))

    history = await store.get_history("c2")
    assert [m.content for m in history] == ["m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_ttl_set_on_messages(fake_redis: Any) -> None:
    store = DialogStateStore(fake_redis, window=20, ttl_seconds=120)
    await store.append_message("c3", DialogMessage(role="user", content="hi"))
    ttl = await fake_redis.ttl("dialog:c3:messages")
    assert 0 < ttl <= 120


@pytest.mark.asyncio
async def test_human_takeover_flag(fake_redis: Any) -> None:
    store = DialogStateStore(fake_redis, window=20, ttl_seconds=60)
    assert await store.is_human_takeover("c4") is False
    await store.set_human_takeover("c4")
    assert await store.is_human_takeover("c4") is True
    await store.clear_human_takeover("c4")
    assert await store.is_human_takeover("c4") is False


@pytest.mark.asyncio
async def test_dedup_setnx(fake_redis: Any) -> None:
    store = DialogStateStore(fake_redis, dedup_ttl_seconds=60)
    assert await store.mark_seen("m-1") is True
    assert await store.mark_seen("m-1") is False


@pytest.mark.asyncio
async def test_outgoing_sent_marker(fake_redis: Any) -> None:
    store = DialogStateStore(fake_redis, outgoing_sent_ttl_seconds=60)
    assert await store.is_our_outgoing("out-1") is False
    await store.mark_outgoing_sent("out-1")
    assert await store.is_our_outgoing("out-1") is True
    ttl = await fake_redis.ttl("outgoing:sent:out-1")
    assert 0 < ttl <= 60


@pytest.mark.asyncio
async def test_outgoing_sent_custom_ttl(fake_redis: Any) -> None:
    store = DialogStateStore(fake_redis, outgoing_sent_ttl_seconds=60)
    await store.mark_outgoing_sent("out-2", ttl=10)
    ttl = await fake_redis.ttl("outgoing:sent:out-2")
    assert 0 < ttl <= 10
