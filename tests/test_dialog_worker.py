"""Echo deduplication + operator-takeover gating in dialog worker."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import Settings
from app.dialog.state import DialogStateStore
from app.wazzup.schemas import WazzupMessage
from app.workers import dialog_worker
from app.workers.dialog_worker import _process_message


def _echo_msg(
    *,
    chat_id: str = "79999648246",
    message_id: str = "echo-msg-1",
    text: str = "Здравствуйте! Чем могу помочь?",
) -> WazzupMessage:
    return WazzupMessage.model_validate(
        {
            "messageId": message_id,
            "channelId": "chan-1",
            "chatType": "whatsapp",
            "chatId": chat_id,
            "type": "text",
            "status": "sent",
            "isEcho": True,
            "text": text,
            "dateTime": datetime.now(UTC).isoformat(),
        }
    )


class _ExplodingAgent:
    async def run(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("agent.run() must not be called for echo branch")


class _ExplodingWazzup:
    async def send_message(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("wazzup.send_message() must not be called for echo branch")


class _SpyState:
    """Минимальный state-stub: фиксирует вызов set_human_takeover."""

    def __init__(self, *, is_ours: bool) -> None:
        self._is_ours = is_ours
        self.takeover_calls = 0
        self.outgoing_marks: list[str] = []

    async def is_our_outgoing(self, message_id: str) -> bool:
        return self._is_ours

    async def set_human_takeover(self, chat_id: str) -> None:
        self.takeover_calls += 1

    async def mark_outgoing_sent(self, message_id: str, *, ttl: int | None = None) -> None:
        self.outgoing_marks.append(message_id)


@pytest.mark.asyncio
async def test_own_echo_ignored_when_message_id_marked() -> None:
    settings = Settings(enable_operator_takeover_from_echo=True)  # type: ignore[call-arg]
    state = _SpyState(is_ours=True)
    await _process_message(
        settings=settings,
        msg=_echo_msg(),
        state=state,  # type: ignore[arg-type]
        agent=_ExplodingAgent(),  # type: ignore[arg-type]
        wazzup=_ExplodingWazzup(),  # type: ignore[arg-type]
    )
    assert state.takeover_calls == 0


@pytest.mark.asyncio
async def test_echo_branch_disabled_by_flag() -> None:
    settings = Settings(enable_operator_takeover_from_echo=False)  # type: ignore[call-arg]
    state = _SpyState(is_ours=False)
    await _process_message(
        settings=settings,
        msg=_echo_msg(),
        state=state,  # type: ignore[arg-type]
        agent=_ExplodingAgent(),  # type: ignore[arg-type]
        wazzup=_ExplodingWazzup(),  # type: ignore[arg-type]
    )
    assert state.takeover_calls == 0


@pytest.mark.asyncio
async def test_unknown_echo_triggers_takeover(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если messageId не в outgoing: и флаг включён → реальный оператор → takeover."""
    settings = Settings(enable_operator_takeover_from_echo=True)  # type: ignore[call-arg]
    state = _SpyState(is_ours=False)

    called: dict[str, Any] = {"takeover": False, "reserved": False}

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

    def _fake_session_scope() -> _FakeSession:
        return _FakeSession()

    async def _fake_reserve(*_: Any, **__: Any) -> bool:
        called["reserved"] = True
        return True

    async def _fake_get_or_create(*_: Any, **__: Any) -> object:
        return object()

    async def _fake_add_message(*_: Any, **__: Any) -> None:
        return None

    async def _fake_mark_takeover(*_: Any, **__: Any) -> None:
        called["takeover"] = True

    monkeypatch.setattr(dialog_worker, "session_scope", _fake_session_scope)
    monkeypatch.setattr(dialog_worker, "try_reserve_message", _fake_reserve)
    monkeypatch.setattr(dialog_worker.history_repo, "get_or_create_dialog", _fake_get_or_create)
    monkeypatch.setattr(dialog_worker.history_repo, "add_message", _fake_add_message)
    monkeypatch.setattr(dialog_worker.history_repo, "mark_human_takeover", _fake_mark_takeover)

    await _process_message(
        settings=settings,
        msg=_echo_msg(message_id="real-operator-1"),
        state=state,  # type: ignore[arg-type]
        agent=_ExplodingAgent(),  # type: ignore[arg-type]
        wazzup=_ExplodingWazzup(),  # type: ignore[arg-type]
    )

    assert state.takeover_calls == 1
    assert called == {"reserved": True, "takeover": True}


@pytest.mark.asyncio
async def test_mark_outgoing_after_send_via_state(fake_redis: Any) -> None:
    """Контракт WazzupClient → DialogStateStore: messageId сохраняется в outgoing:sent:*."""
    from app.wazzup.client import _extract_message_id

    store = DialogStateStore(fake_redis, outgoing_sent_ttl_seconds=60)
    response = {"messageId": "wz-123"}
    message_id = _extract_message_id(response)
    assert message_id == "wz-123"

    await store.mark_outgoing_sent(message_id)
    assert await store.is_our_outgoing("wz-123") is True
    assert await store.is_our_outgoing("other") is False


def test_extract_message_id_handles_nested_data() -> None:
    from app.wazzup.client import _extract_message_id

    assert _extract_message_id({"messageId": "a"}) == "a"
    assert _extract_message_id({"data": {"messageId": "b"}}) == "b"
    assert _extract_message_id({"data": {}}) is None
    assert _extract_message_id({}) is None
