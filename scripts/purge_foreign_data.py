"""Purge data that belongs to chat_ids outside the Wazzup whitelist.

Usage::

    docker compose exec -T app python -m scripts.purge_foreign_data

Безопасность:
- При пустом ``WAZZUP_ALLOWED_CHAT_IDS`` скрипт отказывается работать.
- Удаление выполняется в одной транзакции; при ошибке всё откатывается.
- В Redis удаляются только ключи, которые нельзя оставить (см. ниже).
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator

from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import Dialog, Message, ProcessedMessage
from app.db.session import dispose_engine, session_scope
from app.wazzup.whitelist import normalize_chat_id


async def _iter_redis_keys(redis: Redis[bytes], pattern: str) -> AsyncIterator[str]:
    async for key in redis.scan_iter(match=pattern, count=500):
        yield key.decode() if isinstance(key, (bytes, bytearray)) else str(key)


def _chat_id_from_dialog_key(key: str) -> str | None:
    """``dialog:<chat_id>:messages`` → ``<chat_id>`` (или None если шаблон чужой)."""
    parts = key.split(":")
    if len(parts) >= 3 and parts[0] == "dialog":
        return parts[1]
    return None


async def _purge() -> int:
    settings = get_settings()
    allowed = [normalize_chat_id(item) for item in settings.wazzup_allowed_chat_ids if item]
    if not allowed:
        print(
            "REFUSING TO RUN: WAZZUP_ALLOWED_CHAT_IDS is empty. "
            "Set it to the production whitelist before purging.",
            file=sys.stderr,
        )
        return 2

    allowed_set = set(allowed)
    print(f"Whitelist (normalized): {sorted(allowed_set)}")

    foreign_message_ids: set[str] = set()
    foreign_dialog_chat_ids: set[str] = set()
    deleted_dialogs = 0
    deleted_messages = 0
    deleted_processed = 0

    async with session_scope() as session:
        dialog_rows = (await session.execute(select(Dialog.id, Dialog.chat_id))).all()
        foreign_dialog_ids: list[int] = []
        for dialog_id, chat_id in dialog_rows:
            if normalize_chat_id(chat_id) not in allowed_set:
                foreign_dialog_ids.append(dialog_id)
                foreign_dialog_chat_ids.add(chat_id)

        if foreign_dialog_ids:
            msg_rows = (
                await session.execute(
                    select(Message.wazzup_message_id).where(
                        Message.dialog_id.in_(foreign_dialog_ids),
                        Message.wazzup_message_id.is_not(None),
                    )
                )
            ).all()
            for (wzid,) in msg_rows:
                if wzid:
                    foreign_message_ids.add(wzid)

            deleted_messages = (
                await session.execute(
                    delete(Message).where(Message.dialog_id.in_(foreign_dialog_ids))
                )
            ).rowcount or 0

            deleted_dialogs = (
                await session.execute(delete(Dialog).where(Dialog.id.in_(foreign_dialog_ids)))
            ).rowcount or 0

        processed_rows = (
            await session.execute(
                select(ProcessedMessage.wazzup_message_id, ProcessedMessage.chat_id)
            )
        ).all()
        foreign_processed_ids: list[str] = []
        for wzid, chat_id in processed_rows:
            if chat_id is None:
                continue
            if normalize_chat_id(chat_id) not in allowed_set:
                foreign_processed_ids.append(wzid)
                foreign_message_ids.add(wzid)

        if foreign_processed_ids:
            deleted_processed = (
                await session.execute(
                    delete(ProcessedMessage).where(
                        ProcessedMessage.wazzup_message_id.in_(foreign_processed_ids)
                    )
                )
            ).rowcount or 0

    redis: Redis[bytes] = Redis.from_url(settings.redis_url, decode_responses=False)
    deleted_redis_dialog = 0
    deleted_redis_outgoing = 0
    deleted_redis_dedup = 0
    try:
        async for key in _iter_redis_keys(redis, "dialog:*"):
            chat_id = _chat_id_from_dialog_key(key)
            if chat_id is None:
                continue
            if normalize_chat_id(chat_id) in allowed_set:
                continue
            deleted = await redis.delete(key)
            if deleted:
                deleted_redis_dialog += int(deleted)

        async for key in _iter_redis_keys(redis, "outgoing:sent:*"):
            deleted = await redis.delete(key)
            if deleted:
                deleted_redis_outgoing += int(deleted)

        if foreign_message_ids:
            batch: list[str] = []
            for wzid in foreign_message_ids:
                batch.append(f"wazzup:dedup:{wzid}")
                if len(batch) >= 500:
                    deleted_redis_dedup += int(await redis.delete(*batch))
                    batch.clear()
            if batch:
                deleted_redis_dedup += int(await redis.delete(*batch))
    finally:
        await redis.aclose()

    print("--- Purge summary ---")
    print(f"Foreign dialogs deleted        : {deleted_dialogs}")
    print(f"  chat_ids                     : {sorted(foreign_dialog_chat_ids)}")
    print(f"Foreign messages deleted       : {deleted_messages}")
    print(f"Foreign processed_messages     : {deleted_processed}")
    print(f"Redis dialog:* keys removed    : {deleted_redis_dialog}")
    print(f"Redis outgoing:sent:* removed  : {deleted_redis_outgoing}")
    print(f"Redis wazzup:dedup:* removed   : {deleted_redis_dedup}")
    return 0


async def _main() -> int:
    try:
        return await _purge()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
