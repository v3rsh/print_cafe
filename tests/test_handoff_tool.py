"""Tests for the ``handoff_to_human`` tool and BD idempotency."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dialog
from app.dialog import history as history_repo
from app.dialog.idempotency import try_reserve_message
from app.dialog.state import DialogStateStore
from app.tools.handoff import (
    HANDOFF_REASONS,
    HANDOFF_TOOL_SCHEMA,
    execute_handoff,
    normalise_reason,
)


def test_handoff_tool_schema_shape() -> None:
    schema = HANDOFF_TOOL_SCHEMA
    assert schema["type"] == "function"
    fn = schema["function"]
    assert isinstance(fn, dict)
    assert fn["name"] == "handoff_to_human"
    params = fn["parameters"]
    assert isinstance(params, dict)
    assert params["required"] == ["reason"]
    enum = set(params["properties"]["reason"]["enum"])
    assert enum == HANDOFF_REASONS


def test_normalise_reason() -> None:
    assert normalise_reason("manager_requested") == "manager_requested"
    assert normalise_reason("Manager Requested") == "manager_requested"
    assert normalise_reason("garbage") == "unclear"
    assert normalise_reason(None) == "unclear"
    assert normalise_reason("") == "unclear"


@pytest.mark.asyncio
async def test_execute_handoff_marks_dialog_and_state(
    db_session: AsyncSession,
    fake_redis: Any,
) -> None:
    state = DialogStateStore(fake_redis)
    dialog = await history_repo.get_or_create_dialog(
        db_session,
        chat_id="chat-1",
        channel_id="chan-1",
        chat_type="whatsapp",
    )
    await db_session.commit()

    wazzup = AsyncMock()
    wazzup.add_tag = AsyncMock(return_value=None)

    result = await execute_handoff(
        session=db_session,
        state=state,
        wazzup=wazzup,
        dialog=dialog,
        reason="precise_quote",
    )
    await db_session.commit()

    assert result.triggered is True
    assert result.reason == "precise_quote"
    assert result.tag_pushed is True
    wazzup.add_tag.assert_awaited_once_with(chat_id="chat-1", tag="human_needed:precise_quote")
    assert await state.is_human_takeover("chat-1") is True

    refreshed = await db_session.get(Dialog, dialog.id)
    assert refreshed is not None
    assert refreshed.status == "human"
    assert refreshed.human_takeover_at is not None


@pytest.mark.asyncio
async def test_execute_handoff_survives_wazzup_failure(
    db_session: AsyncSession,
    fake_redis: Any,
) -> None:
    state = DialogStateStore(fake_redis)
    dialog = await history_repo.get_or_create_dialog(
        db_session, chat_id="c2", channel_id="ch1", chat_type="telegram"
    )
    await db_session.commit()

    wazzup = AsyncMock()
    wazzup.add_tag = AsyncMock(side_effect=RuntimeError("boom"))

    result = await execute_handoff(
        session=db_session,
        state=state,
        wazzup=wazzup,
        dialog=dialog,
        reason="complaint",
    )

    assert result.triggered is True
    assert result.tag_pushed is False
    assert await state.is_human_takeover("c2") is True


@pytest.mark.asyncio
async def test_try_reserve_message_dedup(db_session: AsyncSession) -> None:
    first = await try_reserve_message(
        db_session, wazzup_message_id="m-1", chat_id="c1", channel_id="ch1"
    )
    assert first is True

    second = await try_reserve_message(
        db_session, wazzup_message_id="m-1", chat_id="c1", channel_id="ch1"
    )
    assert second is False

    third = await try_reserve_message(
        db_session, wazzup_message_id="m-2", chat_id="c1", channel_id="ch1"
    )
    assert third is True
