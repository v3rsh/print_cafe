"""Persistent (PostgreSQL) dialog & message storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dialog, Message


async def get_or_create_dialog(
    session: AsyncSession,
    *,
    chat_id: str,
    channel_id: str,
    chat_type: str | None = None,
    contact_id: str | None = None,
) -> Dialog:
    stmt = select(Dialog).where(Dialog.chat_id == chat_id, Dialog.channel_id == channel_id)
    dialog = (await session.execute(stmt)).scalar_one_or_none()
    if dialog is not None:
        if chat_type and dialog.chat_type != chat_type:
            dialog.chat_type = chat_type
        if contact_id and dialog.contact_id != contact_id:
            dialog.contact_id = contact_id
        return dialog

    dialog = Dialog(
        chat_id=chat_id,
        channel_id=channel_id,
        chat_type=chat_type,
        contact_id=contact_id,
    )
    session.add(dialog)
    await session.flush()
    return dialog


async def add_message(
    session: AsyncSession,
    *,
    dialog: Dialog,
    role: str,
    content: str,
    wazzup_message_id: str | None = None,
    llm_meta: dict[str, Any] | None = None,
) -> Message:
    message = Message(
        dialog_id=dialog.id,
        role=role,
        content=content,
        wazzup_message_id=wazzup_message_id,
        llm_meta=llm_meta,
    )
    session.add(message)
    dialog.last_message_at = datetime.now(UTC)
    await session.flush()
    return message


async def mark_human_takeover(session: AsyncSession, dialog: Dialog) -> None:
    dialog.status = "human"
    dialog.human_takeover_at = datetime.now(UTC)
    await session.flush()
