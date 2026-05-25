"""Dialog worker: вычитывает Wazzup-сообщения из Redis Stream и ведёт диалог."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.config import Settings, get_settings
from app.db.session import session_scope
from app.dialog import history as history_repo
from app.dialog.idempotency import try_reserve_message
from app.dialog.state import DialogStateStore
from app.llm.agent import Agent
from app.llm.client import YandexGPTClient
from app.logging_config import configure_logging
from app.tools.handoff import execute_handoff
from app.wazzup.client import WazzupClient, WazzupClientError
from app.wazzup.schemas import WazzupMessage
from app.wazzup.whitelist import is_chat_allowed, normalize_chat_id

logger = logging.getLogger(__name__)


async def _ensure_group(redis: Redis[bytes], stream: str, group: str) -> None:
    try:
        await redis.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
        logger.debug("group_already_exists", extra={"group": group})


def _parse_payload(value: bytes | str) -> dict[str, Any]:
    raw = value.decode() if isinstance(value, bytes) else value
    return cast("dict[str, Any]", json.loads(raw))


def _normalize_chat_id(chat_id: str) -> str:
    """Thin alias preserved for tests; canonical impl lives in app.wazzup.whitelist."""
    return normalize_chat_id(chat_id)


def _is_chat_allowed(settings: Settings, chat_id: str) -> bool:
    """Thin alias preserved for tests; canonical impl lives in app.wazzup.whitelist."""
    return is_chat_allowed(settings.wazzup_allowed_chat_ids, chat_id)


async def _process_message(
    *,
    settings: Settings,
    msg: WazzupMessage,
    state: DialogStateStore,
    agent: Agent,
    wazzup: WazzupClient,
) -> None:
    chat_id = msg.chat_id
    channel_id = msg.channel_id
    chat_type = str(msg.chat_type)

    is_inbound = (msg.status or "").lower() == "inbound"
    is_outgoing_operator = msg.is_echo and not is_inbound

    if msg.is_deleted:
        logger.info("skip_deleted_message", extra={"message_id": msg.message_id})
        return

    if not _is_chat_allowed(settings, chat_id):
        logger.debug(
            "foreign_chat_dropped_at_worker",
            extra={"chat_id": chat_id, "channel_id": channel_id},
        )
        return

    if is_outgoing_operator:
        if await state.is_our_outgoing(msg.message_id):
            logger.info(
                "own_echo_ignored",
                extra={"message_id": msg.message_id, "chat_id": chat_id},
            )
            return

        if not settings.enable_operator_takeover_from_echo:
            logger.info(
                "operator_takeover_disabled",
                extra={"message_id": msg.message_id, "chat_id": chat_id},
            )
            return

        async with session_scope() as session:
            reserved = await try_reserve_message(
                session,
                wazzup_message_id=msg.message_id,
                chat_id=chat_id,
                channel_id=channel_id,
            )
            if not reserved:
                logger.info("skip_duplicate_operator_msg", extra={"message_id": msg.message_id})
                return
            await state.set_human_takeover(chat_id)
            dialog = await history_repo.get_or_create_dialog(
                session,
                chat_id=chat_id,
                channel_id=channel_id,
                chat_type=chat_type,
            )
            if msg.text:
                await history_repo.add_message(
                    session,
                    dialog=dialog,
                    role="operator",
                    content=msg.text,
                    wazzup_message_id=msg.message_id,
                )
            await history_repo.mark_human_takeover(session, dialog)
        logger.info("operator_takeover", extra={"chat_id": chat_id})
        return

    if not is_inbound:
        return

    text = (msg.text or "").strip()
    if not text:
        logger.info("skip_non_text_message", extra={"type": msg.type})
        return

    async with session_scope() as session:
        reserved = await try_reserve_message(
            session,
            wazzup_message_id=msg.message_id,
            chat_id=chat_id,
            channel_id=channel_id,
        )
        if not reserved:
            logger.info(
                "skip_duplicate_inbound", extra={"message_id": msg.message_id, "chat_id": chat_id}
            )
            return
        dialog = await history_repo.get_or_create_dialog(
            session,
            chat_id=chat_id,
            channel_id=channel_id,
            chat_type=chat_type,
            contact_id=msg.contact.username if msg.contact else None,
        )
        await history_repo.add_message(
            session,
            dialog=dialog,
            role="user",
            content=text,
            wazzup_message_id=msg.message_id,
        )

    reply = await agent.run(
        chat_id=chat_id,
        user_message=text,
        state=state,
    )
    if reply.skipped:
        logger.info(
            "dialog_skipped",
            extra={"chat_id": chat_id, "reason": reply.skip_reason},
        )
        return

    for piece in reply.messages:
        try:
            await wazzup.send_message(
                channel_id=channel_id,
                chat_id=chat_id,
                chat_type=chat_type,
                text=piece,
            )
        except WazzupClientError:
            logger.exception("send_message_failed", extra={"chat_id": chat_id})
            break

    async with session_scope() as session:
        dialog = await history_repo.get_or_create_dialog(
            session,
            chat_id=chat_id,
            channel_id=channel_id,
            chat_type=chat_type,
        )
        await history_repo.add_message(
            session,
            dialog=dialog,
            role="assistant",
            content=reply.raw,
            llm_meta={
                "handoff_reason": reply.handoff.reason if reply.handoff else None,
                "messages_count": len(reply.messages),
            },
        )

        if reply.needs_handoff and reply.handoff is not None:
            await execute_handoff(
                session=session,
                state=state,
                wazzup=wazzup,
                dialog=dialog,
                reason=reply.handoff.reason,
            )


async def _process_envelope(
    *,
    settings: Settings,
    fields: dict[bytes | str, bytes | str],
    state: DialogStateStore,
    agent: Agent,
    wazzup: WazzupClient,
) -> None:
    str_fields = {(k.decode() if isinstance(k, bytes) else k): v for k, v in fields.items()}
    kind_raw = str_fields.get("kind", b"")
    kind = kind_raw.decode() if isinstance(kind_raw, bytes) else kind_raw
    payload_raw = str_fields.get("payload", b"")
    if not payload_raw:
        return

    if kind != "message":
        # Statuses / other kinds are ignored in MVP - we only react to messages.
        logger.debug("skip_envelope", extra={"kind": kind})
        return

    data = _parse_payload(payload_raw)
    msg = WazzupMessage.model_validate(data)
    await _process_message(
        settings=settings,
        msg=msg,
        state=state,
        agent=agent,
        wazzup=wazzup,
    )


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    logger.info("dialog_worker_starting", extra={"stream": settings.wazzup_incoming_stream})

    redis: Redis[bytes] = Redis.from_url(settings.redis_url, decode_responses=False)
    await _ensure_group(redis, settings.wazzup_incoming_stream, settings.wazzup_incoming_group)

    state = DialogStateStore(
        redis,  # type: ignore[arg-type]  # bytes-typed Redis matches the Protocol shape
        window=settings.dialog_history_window,
        ttl_seconds=settings.dialog_history_ttl_seconds,
        dedup_ttl_seconds=settings.wazzup_dedup_ttl_seconds,
        outgoing_sent_ttl_seconds=settings.wazzup_outgoing_sent_ttl_seconds,
    )
    llm = YandexGPTClient(
        api_key=settings.yandex_api_key.get_secret_value(),
        folder_id=settings.yandex_folder_id,
        model=settings.yandex_model_resolved,
        base_url=settings.yandex_base_url,
        temperature=settings.yandex_temperature,
        max_tokens=settings.yandex_max_tokens,
        data_logging_enabled=settings.yandex_data_logging_enabled,
    )
    wazzup = WazzupClient(
        api_key=settings.wazzup_api_key.get_secret_value(),
        base_url=settings.wazzup_api_base_url,
        outgoing_tracker=state,
    )
    agent = Agent(llm)

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        logger.info("dialog_worker_stop_requested")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - Windows
            signal.signal(sig, lambda *_: _request_stop())

    try:
        while not stop_event.is_set():
            response = await redis.xreadgroup(
                groupname=settings.wazzup_incoming_group,
                consumername=settings.wazzup_incoming_consumer,
                streams={settings.wazzup_incoming_stream: ">"},
                count=10,
                block=5_000,
            )
            if not response:
                continue
            for _stream, entries in response:
                for entry_id, fields in entries:
                    try:
                        await _process_envelope(
                            settings=settings,
                            fields=fields,
                            state=state,
                            agent=agent,
                            wazzup=wazzup,
                        )
                    except Exception:
                        logger.exception(
                            "dialog_worker_entry_failed",
                            extra={"entry_id": entry_id},
                        )
                    finally:
                        await redis.xack(  # type: ignore[no-untyped-call]
                            settings.wazzup_incoming_stream,
                            settings.wazzup_incoming_group,
                            entry_id,
                        )
    finally:
        logger.info("dialog_worker_stopping")
        await wazzup.aclose()
        await llm.aclose()
        await redis.aclose()  # type: ignore[attr-defined]


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
