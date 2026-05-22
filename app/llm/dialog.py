"""High-level dialog handler: оборачивает :class:`app.llm.agent.Agent`.

Этот модуль остаётся точкой входа для воркера и тестов. Реальную работу —
системный промпт, парсинг ответа, реестр инструментов — делает
:class:`Agent`. Здесь только адаптер старого функционального API
``handle_message(chat_id, user_message, state, llm)`` поверх Agent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dialog.state import DialogStateStore
from app.llm.agent import Agent, AgentReply
from app.tools.handoff import HandoffResult


@dataclass(slots=True)
class BotReply:
    """Backward-compatible форма ответа: список сообщений + handoff_reason."""

    messages: list[str]
    handoff_reason: str | None
    raw: str

    @property
    def needs_handoff(self) -> bool:
        return self.handoff_reason is not None


def _to_bot_reply(reply: AgentReply) -> BotReply | None:
    if reply.skipped:
        return None
    handoff_reason: str | None = None
    if reply.handoff is not None and reply.handoff.triggered:
        handoff_reason = reply.handoff.reason
    return BotReply(
        messages=reply.messages,
        handoff_reason=handoff_reason,
        raw=reply.raw,
    )


async def handle_message(
    *,
    chat_id: str,
    user_message: str,
    state: DialogStateStore,
    llm: object,
) -> BotReply | None:
    """Однократная обработка реплики клиента.

    ``llm`` — что-нибудь, у чего есть ``async def chat(messages, ...)``.
    На проде это :class:`app.llm.client.YandexGPTClient`, в тестах — фейк.
    """
    agent = Agent(llm)  # type: ignore[arg-type]
    reply = await agent.run(chat_id=chat_id, user_message=user_message, state=state)
    return _to_bot_reply(reply)


def execute_handoff_marker(reply: BotReply) -> HandoffResult | None:
    """Превращает handoff_reason из reply в HandoffResult-«декларацию»."""
    if not reply.needs_handoff or reply.handoff_reason is None:
        return None
    return HandoffResult(triggered=True, reason=reply.handoff_reason, tag_pushed=False)


__all__ = [
    "BotReply",
    "execute_handoff_marker",
    "handle_message",
]
