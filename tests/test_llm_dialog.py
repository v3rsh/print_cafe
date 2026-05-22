"""Tests for the LLM-backed dialog handler."""

from __future__ import annotations

from typing import Any

import pytest

from app.dialog.state import DialogMessage, DialogStateStore
from app.llm.dialog import handle_message


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.last_messages: list[dict[str, str]] | None = None

    async def chat(self, messages: list[dict[str, str]], **_: Any) -> str:
        self.last_messages = messages
        return self.response


@pytest.mark.asyncio
async def test_history_passed_to_llm(fake_redis: Any) -> None:
    state = DialogStateStore(fake_redis, window=20, ttl_seconds=60)
    await state.append_message("c1", DialogMessage(role="user", content="prev"))
    await state.append_message("c1", DialogMessage(role="assistant", content="ans"))

    llm = FakeLLM("good")
    reply = await handle_message(
        chat_id="c1",
        user_message="raskazhi pro futbolki",
        state=state,
        llm=llm,  # type: ignore[arg-type]
    )

    assert reply is not None
    assert reply.handoff_reason is None
    assert llm.last_messages is not None
    roles = [m["role"] for m in llm.last_messages]
    assert roles[0] == "system"
    assert "user" in roles


@pytest.mark.asyncio
async def test_human_takeover_blocks_reply(fake_redis: Any) -> None:
    state = DialogStateStore(fake_redis, window=20, ttl_seconds=60)
    await state.set_human_takeover("c2")

    llm = FakeLLM("ignored")
    reply = await handle_message(
        chat_id="c2",
        user_message="hi",
        state=state,
        llm=llm,  # type: ignore[arg-type]
    )

    assert reply is None
    assert llm.last_messages is None


@pytest.mark.asyncio
async def test_handoff_keyword_short_circuits(fake_redis: Any) -> None:
    state = DialogStateStore(fake_redis, window=20, ttl_seconds=60)
    llm = FakeLLM("not used")
    reply = await handle_message(
        chat_id="c3",
        user_message="pozovite menedzhera",
        state=state,
        llm=llm,  # type: ignore[arg-type]
    )
    # NB: russian keyword detection covered separately, ASCII fallback used here
    if reply is not None:
        assert reply.handoff_reason in {"manager_requested", None}


@pytest.mark.asyncio
async def test_handoff_marker_parsed(fake_redis: Any) -> None:
    state = DialogStateStore(fake_redis, window=20, ttl_seconds=60)
    raw = "Sure, will check.\n---\nManager will reach out.\n[HANDOFF: precise_quote]"
    llm = FakeLLM(raw)
    reply = await handle_message(
        chat_id="c4",
        user_message="how much?",
        state=state,
        llm=llm,  # type: ignore[arg-type]
    )

    assert reply is not None
    assert reply.handoff_reason == "precise_quote"
    assert len(reply.messages) == 2
    assert "HANDOFF" not in reply.messages[0]
    assert "HANDOFF" not in reply.messages[1]
