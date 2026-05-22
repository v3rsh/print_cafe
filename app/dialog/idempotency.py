"""Идемпотентность входящих вебхуков по wazzup_message_id.

Использование:
    async with session_scope() as session:
        if not await try_reserve_message(session, message_id, chat_id, channel_id):
            return  # уже обрабатывали — пропускаем
        ...

Логика:
- INSERT в `processed_messages` с уникальным PK = wazzup_message_id;
- при конфликте (UniqueViolationError на Postgres / IntegrityError на SQLite)
  возвращаем False и **откатываем** только этот savepoint, чтобы не убить
  всю транзакцию. Используем nested savepoint (`session.begin_nested()`).
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProcessedMessage


async def try_reserve_message(
    session: AsyncSession,
    *,
    wazzup_message_id: str,
    chat_id: str | None = None,
    channel_id: str | None = None,
) -> bool:
    """Возвращает True если сообщение зарезервировано впервые."""
    stamp = ProcessedMessage(
        wazzup_message_id=wazzup_message_id,
        chat_id=chat_id,
        channel_id=channel_id,
    )
    try:
        async with session.begin_nested():
            session.add(stamp)
    except IntegrityError:
        return False
    return True
