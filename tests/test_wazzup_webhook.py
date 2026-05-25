"""Tests for the Wazzup24 webhook endpoint."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import get_settings

_AUTH = {"Authorization": "Bearer test-secret"}


@pytest.mark.asyncio
async def test_test_probe_returns_200(webhook_client: AsyncClient) -> None:
    response = await webhook_client.post(
        "/webhooks/wazzup",
        json={"test": True},
        headers=_AUTH,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_invalid_secret_rejected(webhook_client: AsyncClient) -> None:
    response = await webhook_client.post(
        "/webhooks/wazzup",
        json={"test": True},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_secret_via_query_string(webhook_client: AsyncClient) -> None:
    response = await webhook_client.post(
        "/webhooks/wazzup?secret=test-secret",
        json={"test": True},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_message_pushed_to_stream(
    webhook_client: AsyncClient,
    fake_redis: Any,
) -> None:
    payload = {
        "messages": [
            {
                "messageId": "msg-1",
                "channelId": "chan-1",
                "chatType": "whatsapp",
                "chatId": "79991234567",
                "type": "text",
                "status": "inbound",
                "isEcho": False,
                "text": "Privet",
                "dateTime": "2026-05-22T10:00:00.000Z",
            }
        ]
    }

    response = await webhook_client.post("/webhooks/wazzup", json=payload, headers=_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["duplicates"] == 0

    entries = await fake_redis.xrange("wazzup:incoming")
    assert len(entries) == 1
    _entry_id, fields = entries[0]
    assert fields[b"kind"] == b"message"
    payload_bytes = fields[b"payload"]
    data = json.loads(payload_bytes.decode())
    assert data["messageId"] == "msg-1"
    assert data["text"] == "Privet"


@pytest.mark.asyncio
async def test_duplicate_message_dropped(
    webhook_client: AsyncClient,
    fake_redis: Any,
) -> None:
    payload = {
        "messages": [
            {
                "messageId": "dup-1",
                "channelId": "chan-1",
                "chatType": "whatsapp",
                "chatId": "79991234567",
                "type": "text",
                "status": "inbound",
                "text": "test",
            }
        ]
    }

    first = await webhook_client.post("/webhooks/wazzup", json=payload, headers=_AUTH)
    assert first.json()["accepted"] == 1

    second = await webhook_client.post("/webhooks/wazzup", json=payload, headers=_AUTH)
    assert second.status_code == 200
    assert second.json()["accepted"] == 0
    assert second.json()["duplicates"] == 1

    entries = await fake_redis.xrange("wazzup:incoming")
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_foreign_chat_dropped_at_webhook(
    webhook_client: AsyncClient,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Сообщение от чужого chat_id не должно попасть ни в Stream, ни в dedup."""
    monkeypatch.setenv("WAZZUP_ALLOWED_CHAT_IDS", "79999648246")
    get_settings.cache_clear()

    payload = {
        "messages": [
            {
                "messageId": "foreign-msg-1",
                "channelId": "chan-1",
                "chatType": "whatsapp",
                "chatId": "70000000001",
                "type": "text",
                "status": "inbound",
                "isEcho": False,
                "text": "Should be dropped",
                "dateTime": "2026-05-22T10:00:00.000Z",
            }
        ]
    }

    with caplog.at_level(logging.DEBUG, logger="app.wazzup.webhooks"):
        response = await webhook_client.post("/webhooks/wazzup", json=payload, headers=_AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 0
    assert body["foreign"] == 1

    entries = await fake_redis.xrange("wazzup:incoming")
    assert entries == []
    assert await fake_redis.get("wazzup:dedup:foreign-msg-1") is None

    assert any("foreign_chat_dropped_at_webhook" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_mixed_messages_only_whitelisted_passes(
    webhook_client: AsyncClient,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В одном вебхуке whitelisted и чужой chat_id → в Stream попадает только whitelisted."""
    monkeypatch.setenv("WAZZUP_ALLOWED_CHAT_IDS", "79999648246")
    get_settings.cache_clear()

    payload = {
        "messages": [
            {
                "messageId": "ours-1",
                "channelId": "chan-1",
                "chatType": "whatsapp",
                "chatId": "79999648246",
                "type": "text",
                "status": "inbound",
                "text": "yes",
            },
            {
                "messageId": "foreign-2",
                "channelId": "chan-1",
                "chatType": "whatsapp",
                "chatId": "79001112233",
                "type": "text",
                "status": "inbound",
                "text": "leak?",
            },
        ]
    }

    response = await webhook_client.post("/webhooks/wazzup", json=payload, headers=_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["foreign"] == 1

    entries = await fake_redis.xrange("wazzup:incoming")
    assert len(entries) == 1
    _entry_id, fields = entries[0]
    data = json.loads(fields[b"payload"].decode())
    assert data["chatId"] == "79999648246"
