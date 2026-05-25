"""Whitelist gate for incoming Wazzup messages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import Settings
from app.wazzup.schemas import WazzupMessage
from app.workers.dialog_worker import (
    _is_chat_allowed,
    _normalize_chat_id,
    _process_message,
)


def _msg(chat_id: str, *, message_id: str = "m-1") -> WazzupMessage:
    return WazzupMessage.model_validate(
        {
            "messageId": message_id,
            "channelId": "chan-1",
            "chatType": "whatsapp",
            "chatId": chat_id,
            "type": "text",
            "status": "inbound",
            "isEcho": False,
            "text": "Hello",
            "dateTime": datetime.now(UTC).isoformat(),
        }
    )


class _ExplodingAgent:
    async def run(self, **_: Any) -> Any:  # pragma: no cover - must not be called
        raise AssertionError("agent.run() must not be called for blocked chat")


class _ExplodingWazzup:
    async def send_message(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("wazzup.send_message() must not be called for blocked chat")


class _ExplodingState:
    async def set_human_takeover(self, *_: Any, **__: Any) -> None:  # pragma: no cover
        raise AssertionError("state must not be touched for blocked chat")


def test_normalize_chat_id_strips_plus_and_spaces() -> None:
    assert _normalize_chat_id("+7 999 964 82 46") == "79999648246"
    assert _normalize_chat_id("79999648246") == "79999648246"


def test_is_chat_allowed_empty_list_passes_all() -> None:
    settings = Settings(wazzup_allowed_chat_ids=[])  # type: ignore[call-arg]
    assert _is_chat_allowed(settings, "79991112233") is True


def test_is_chat_allowed_blocks_outsider() -> None:
    settings = Settings(wazzup_allowed_chat_ids=["79999648246"])  # type: ignore[call-arg]
    assert _is_chat_allowed(settings, "79991112233") is False
    assert _is_chat_allowed(settings, "79999648246") is True


def test_is_chat_allowed_normalizes_both_sides() -> None:
    settings = Settings(wazzup_allowed_chat_ids=["+7 999 964 82 46"])  # type: ignore[call-arg]
    assert _is_chat_allowed(settings, "+79999648246") is True


def test_csv_parsing_from_env_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAZZUP_ALLOWED_CHAT_IDS", "+79991112233, 79999648246")
    settings = Settings()
    assert settings.wazzup_allowed_chat_ids == ["79991112233", "79999648246"]


def test_csv_parsing_python_list() -> None:
    settings = Settings(wazzup_allowed_chat_ids="+79991112233, 79999648246")  # type: ignore[arg-type]
    assert settings.wazzup_allowed_chat_ids == ["79991112233", "79999648246"]


@pytest.mark.asyncio
async def test_process_message_blocks_chat_outside_whitelist() -> None:
    settings = Settings(wazzup_allowed_chat_ids=["79999648246"])  # type: ignore[call-arg]
    await _process_message(
        settings=settings,
        msg=_msg("79991112233"),
        state=_ExplodingState(),  # type: ignore[arg-type]
        agent=_ExplodingAgent(),  # type: ignore[arg-type]
        wazzup=_ExplodingWazzup(),  # type: ignore[arg-type]
    )


def _echo_msg(chat_id: str, *, message_id: str = "echo-1") -> WazzupMessage:
    return WazzupMessage.model_validate(
        {
            "messageId": message_id,
            "channelId": "chan-1",
            "chatType": "whatsapp",
            "chatId": chat_id,
            "type": "text",
            "status": "sent",
            "isEcho": True,
            "text": "operator reply",
            "dateTime": datetime.now(UTC).isoformat(),
        }
    )


@pytest.mark.asyncio
async def test_foreign_echo_does_not_touch_db_or_redis(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Эхо оператора по чужому chat_id: НЕ создаём Dialog/Message, НЕ ходим в Redis state."""
    import logging

    from app.workers import dialog_worker

    settings = Settings(  # type: ignore[call-arg]
        wazzup_allowed_chat_ids=["79999648246"],
        enable_operator_takeover_from_echo=True,
    )

    def _explode_session_scope(*_: Any, **__: Any) -> Any:
        raise AssertionError("session_scope() must not be called for blocked chat")

    async def _explode(*_: Any, **__: Any) -> Any:
        raise AssertionError("DB helper must not be called for blocked chat")

    monkeypatch.setattr(dialog_worker, "session_scope", _explode_session_scope)
    monkeypatch.setattr(dialog_worker, "try_reserve_message", _explode)
    monkeypatch.setattr(dialog_worker.history_repo, "get_or_create_dialog", _explode)
    monkeypatch.setattr(dialog_worker.history_repo, "add_message", _explode)
    monkeypatch.setattr(dialog_worker.history_repo, "mark_human_takeover", _explode)

    with caplog.at_level(logging.DEBUG, logger="app.workers.dialog_worker"):
        await _process_message(
            settings=settings,
            msg=_echo_msg("70000000001"),
            state=_ExplodingState(),  # type: ignore[arg-type]
            agent=_ExplodingAgent(),  # type: ignore[arg-type]
            wazzup=_ExplodingWazzup(),  # type: ignore[arg-type]
        )

    assert any("foreign_chat_dropped_at_worker" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_foreign_inbound_does_not_touch_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inbound от чужого chat_id: НИ ОДНОГО обращения к БД / state."""
    from app.workers import dialog_worker

    settings = Settings(wazzup_allowed_chat_ids=["79999648246"])  # type: ignore[call-arg]

    def _explode_session_scope(*_: Any, **__: Any) -> Any:
        raise AssertionError("session_scope() must not be called for blocked chat")

    async def _explode(*_: Any, **__: Any) -> Any:
        raise AssertionError("DB helper must not be called for blocked chat")

    monkeypatch.setattr(dialog_worker, "session_scope", _explode_session_scope)
    monkeypatch.setattr(dialog_worker, "try_reserve_message", _explode)
    monkeypatch.setattr(dialog_worker.history_repo, "get_or_create_dialog", _explode)
    monkeypatch.setattr(dialog_worker.history_repo, "add_message", _explode)

    await _process_message(
        settings=settings,
        msg=_msg("70000000001"),
        state=_ExplodingState(),  # type: ignore[arg-type]
        agent=_ExplodingAgent(),  # type: ignore[arg-type]
        wazzup=_ExplodingWazzup(),  # type: ignore[arg-type]
    )
