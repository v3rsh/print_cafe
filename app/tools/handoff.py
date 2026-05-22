"""Tool ``handoff_to_human``: передача диалога живому менеджеру.

Эффект:
1. БД: ставим ``Dialog.status='human'`` и ``human_takeover_at=now``.
2. Wazzup: пытаемся проставить тег ``human_needed:<reason>`` через
   ``WazzupClient.add_tag``. У некоторых тарифов Wazzup нет ручки тегов —
   тогда метод деградирует до warning-лога; диалог в БД всё равно помечен.
3. Redis: ``DialogStateStore.set_human_takeover`` — чтобы дальнейшие
   входящие в этот чат не запускали LLM до тех пор, пока менеджер не
   снимет блок.

Tool вызывается агентом; реальные побочные эффекты идут через
:func:`execute_handoff`. Схема в :data:`HANDOFF_TOOL_SCHEMA` соответствует
формату ``tools=[{"type": "function", "function": {...}}]`` OpenAI API,
готова к подключению native function calling, когда YandexGPT 5.1 Pro
стабилизирует совместимость.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.db.models import Dialog
from app.dialog.history import mark_human_takeover
from app.dialog.state import DialogStateStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.wazzup.client import WazzupClient

logger = logging.getLogger(__name__)


HANDOFF_REASONS = {
    "manager_requested",
    "precise_quote",
    "complaint",
    "existing_order",
    "non_standard",
    "policy_question",
    "unclear",
}


HANDOFF_TOOL_SCHEMA: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "handoff_to_human",
        "description": (
            "Передать диалог живому менеджеру Print Cafe. Используй,"
            " когда без человека не обойтись: явная просьба клиента,"
            " претензия, упоминание существующего заказа, нужна"
            " точная цена/срок, нестандартный запрос."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": sorted(HANDOFF_REASONS),
                    "description": "Категория причины передачи.",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
}


@dataclass(slots=True)
class HandoffResult:
    """Что произошло после вызова инструмента."""

    triggered: bool
    reason: str
    tag_pushed: bool


def normalise_reason(raw: str | None) -> str:
    if not raw:
        return "unclear"
    cleaned = raw.strip().lower().replace(" ", "_")
    if cleaned not in HANDOFF_REASONS:
        return "unclear"
    return cleaned


async def execute_handoff(
    *,
    session: AsyncSession,
    state: DialogStateStore,
    wazzup: WazzupClient | None,
    dialog: Dialog,
    reason: str,
) -> HandoffResult:
    """Реализация tool: пишет в БД, в Redis и (по возможности) в Wazzup."""
    safe_reason = normalise_reason(reason)
    await mark_human_takeover(session, dialog)
    await state.set_human_takeover(dialog.chat_id)

    tag_pushed = False
    if wazzup is not None:
        try:
            await wazzup.add_tag(
                chat_id=dialog.chat_id,
                tag=f"human_needed:{safe_reason}",
            )
            tag_pushed = True
        except Exception:
            logger.exception(
                "handoff_tag_failed",
                extra={"chat_id": dialog.chat_id, "reason": safe_reason},
            )

    logger.info(
        "handoff_executed",
        extra={
            "dialog_id": dialog.id,
            "chat_id": dialog.chat_id,
            "channel_id": dialog.channel_id,
            "reason": safe_reason,
            "tag_pushed": tag_pushed,
        },
    )
    return HandoffResult(triggered=True, reason=safe_reason, tag_pushed=tag_pushed)
