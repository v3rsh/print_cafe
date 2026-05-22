"""High-level dialog handler: from a user message to bot replies."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.dialog.state import DialogMessage, DialogStateStore
from app.llm.client import YandexGPTClient
from app.llm.prompts import build_system_messages

logger = logging.getLogger(__name__)

_HANDOFF_RE = re.compile(r"\[HANDOFF:\s*([a-z_]+)\s*\]", re.IGNORECASE)
_SPLIT_RE = re.compile(r"\n-{2,}\n")


@dataclass(slots=True)
class BotReply:
    messages: list[str]
    handoff_reason: str | None
    raw: str

    @property
    def needs_handoff(self) -> bool:
        return self.handoff_reason is not None


def _parse_reply(raw: str) -> BotReply:
    handoff_reason: str | None = None
    match = _HANDOFF_RE.search(raw)
    if match:
        handoff_reason = match.group(1).lower()
        cleaned = _HANDOFF_RE.sub("", raw)
    else:
        cleaned = raw

    parts = [chunk.strip() for chunk in _SPLIT_RE.split(cleaned) if chunk.strip()]
    if not parts:
        parts = [cleaned.strip()]
    parts = [p for p in parts if p]
    return BotReply(messages=parts, handoff_reason=handoff_reason, raw=raw)


_MANAGER_KEYWORDS = (
    "менеджер",
    "оператор",
    "человек",
    "живой",
    "сотрудник",
    "позови",
    "позовите",
)


def _wants_human(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in _MANAGER_KEYWORDS)


async def handle_message(
    *,
    chat_id: str,
    user_message: str,
    state: DialogStateStore,
    llm: YandexGPTClient,
) -> BotReply | None:
    if await state.is_human_takeover(chat_id):
        await state.append_message(chat_id, DialogMessage(role="user", content=user_message))
        logger.info("dialog_skipped_takeover", extra={"chat_id": chat_id})
        return None

    await state.append_message(chat_id, DialogMessage(role="user", content=user_message))
    history = await state.get_history(chat_id)

    if _wants_human(user_message):
        text = (
            "Конечно, передаю диалог менеджеру - он на связи в рабочие часы.\n"
            "Пока он подключается, могу подсказать что-то по продукции?"
        )
        reply = BotReply(messages=text.split("\n"), handoff_reason="manager_requested", raw=text)
        await state.append_message(chat_id, DialogMessage(role="assistant", content=text))
        return reply

    messages: list[dict[str, str]] = build_system_messages()
    for entry in history:
        role = entry.role if entry.role in {"user", "assistant", "system"} else "user"
        messages.append({"role": role, "content": entry.content})

    raw_response = await llm.chat(messages)
    reply = _parse_reply(raw_response)

    await state.append_message(
        chat_id,
        DialogMessage(role="assistant", content=raw_response),
    )
    return reply
