"""Agent: тонкая обёртка над YandexGPTClient + tool registry.

Архитектурно агент — это «LLM + список инструментов + механизм триггера
инструментов». Текущая фаза:

* Список инструментов: один — :data:`app.tools.handoff.HANDOFF_TOOL_SCHEMA`.
* Механизм триггера: специальный маркер ``[HANDOFF: <reason>]`` в ответе
  модели (см. system prompt). Маркер парсится через regex, по нему
  выполняется реальный python-инструмент :func:`execute_handoff`.

Почему не native function calling
=================================
В ТЗ допускается выбор: «pydantic-ai с tool calling, либо прямые вызовы
openai SDK + function calling и обёртка поверх — выбери лучшее решение и
обоснуй». На дату MVP YandexGPT 5.1 Pro выставлен через OpenAI-совместимый
endpoint, но поддержка ``tools`` в их слое совместимости менялась несколько
раз и в продакшене ведёт себя неустойчиво (известны кейсы, когда модель
игнорирует ``tool_choice`` или возвращает строку вместо ``tool_calls``).
Маркер же триггерится **самой моделью** через дисциплину системного
промпта — это надёжно и проверяемо в респонсах.

Этот класс держит реестр инструментов как раз для того, чтобы при
переезде на native function calling в следующей фазе достаточно было
поменять реализацию :meth:`Agent.run` без правок вызывающего кода.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from app.dialog.state import DialogMessage, DialogStateStore
from app.llm.prompts import build_system_messages
from app.tools.handoff import (
    HANDOFF_TOOL_SCHEMA,
    HandoffResult,
    normalise_reason,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_HANDOFF_RE = re.compile(r"\[HANDOFF:\s*([a-z_]+)\s*\]", re.IGNORECASE)
_SPLIT_RE = re.compile(r"\n-{2,}\n")
_MANAGER_KEYWORDS = (
    "менеджер",
    "оператор",
    "человек",
    "живой",
    "сотрудник",
    "позови",
    "позовите",
)


class _ChatLLM(Protocol):
    """Минимальный контракт LLM, который ждёт агент."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = ...,
        max_tokens: int | None = ...,
    ) -> str: ...


@dataclass(slots=True)
class AgentReply:
    """Итог одного шага диалога."""

    messages: list[str] = field(default_factory=list)
    raw: str = ""
    handoff: HandoffResult | None = None
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def needs_handoff(self) -> bool:
        return self.handoff is not None and self.handoff.triggered


def _parse_messages(raw: str) -> tuple[list[str], str | None]:
    """Возвращает (отдельные_сообщения, handoff_reason_or_None)."""
    handoff_reason: str | None = None
    match = _HANDOFF_RE.search(raw)
    cleaned = raw
    if match:
        handoff_reason = normalise_reason(match.group(1))
        cleaned = _HANDOFF_RE.sub("", raw)
    parts = [chunk.strip() for chunk in _SPLIT_RE.split(cleaned) if chunk.strip()]
    if not parts:
        stripped = cleaned.strip()
        parts = [stripped] if stripped else []
    return parts, handoff_reason


def detect_explicit_handoff_request(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in _MANAGER_KEYWORDS)


@dataclass(slots=True)
class _ToolDef:
    name: str
    schema: dict[str, object]


class Agent:
    """LLM + реестр инструментов.

    Используется dialog worker'ом. Отвечает за:
    1. Подгрузку системного промпта и истории в формат для LLM.
    2. Вызов LLM (через :class:`_ChatLLM`).
    3. Парсинг ответа: разбивка на отдельные сообщения, извлечение
       handoff-маркера.
    4. Регистрация инструмента ``handoff_to_human``: сама задача побочных
       эффектов handoff'а делегируется наружу — :func:`run_with_tools`,
       чтобы агент оставался синхронным и легко тестируемым.
    """

    def __init__(self, llm: _ChatLLM) -> None:
        self._llm = llm
        self._tools: list[_ToolDef] = [
            _ToolDef(name="handoff_to_human", schema=HANDOFF_TOOL_SCHEMA),
        ]

    @property
    def tools(self) -> list[dict[str, object]]:
        return [t.schema for t in self._tools]

    async def run(
        self,
        *,
        chat_id: str,
        user_message: str,
        state: DialogStateStore,
    ) -> AgentReply:
        if await state.is_human_takeover(chat_id):
            await state.append_message(chat_id, DialogMessage(role="user", content=user_message))
            return AgentReply(skipped=True, skip_reason="human_takeover")

        await state.append_message(chat_id, DialogMessage(role="user", content=user_message))

        if detect_explicit_handoff_request(user_message):
            text = (
                "Передаю диалог менеджеру — он на связи в рабочие часы.\n"
                "Если хотите, пока подскажу что-то по продукции или печати."
            )
            await state.append_message(chat_id, DialogMessage(role="assistant", content=text))
            return AgentReply(
                messages=[line for line in text.split("\n") if line.strip()],
                raw=text,
                handoff=HandoffResult(
                    triggered=True,
                    reason="manager_requested",
                    tag_pushed=False,
                ),
            )

        history = await state.get_history(chat_id)
        messages: list[dict[str, str]] = build_system_messages()
        for entry in history:
            role = entry.role if entry.role in {"user", "assistant", "system"} else "user"
            messages.append({"role": role, "content": entry.content})

        raw_response = await self._llm.chat(messages)
        parts, handoff_reason = _parse_messages(raw_response)

        await state.append_message(chat_id, DialogMessage(role="assistant", content=raw_response))

        handoff: HandoffResult | None = None
        if handoff_reason is not None:
            # Реальный side-effect (БД/Wazzup/Redis) делает воркер через
            # execute_handoff(...), сюда возвращаем «декларацию о намерении».
            handoff = HandoffResult(
                triggered=True,
                reason=handoff_reason,
                tag_pushed=False,
            )
        return AgentReply(
            messages=parts or [raw_response.strip() or ""],
            raw=raw_response,
            handoff=handoff,
        )


__all__ = [
    "Agent",
    "AgentReply",
    "detect_explicit_handoff_request",
]
