"""FastAPI router that ingests Wazzup24 webhooks."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.dialog.state import DialogStateStore
from app.wazzup.schemas import WazzupWebhookPayload
from app.wazzup.whitelist import is_chat_allowed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["wazzup"])


def _verify_secret(
    settings: Settings,
    *,
    auth_header: str | None,
    secret_query: str | None,
) -> None:
    expected = settings.wazzup_webhook_secret.get_secret_value()
    if not expected:
        logger.warning("wazzup_webhook_unprotected")
        return

    candidate: str | None = None
    if auth_header and auth_header.lower().startswith("bearer "):
        candidate = auth_header.split(" ", 1)[1].strip()
    if candidate is None and secret_query:
        candidate = secret_query

    if candidate != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _redis_from_request(request: Request) -> Redis[bytes]:
    redis: Redis[bytes] | None = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis connection is not initialised",
        )
    return redis


@router.post("/wazzup", status_code=status.HTTP_200_OK)
async def receive_wazzup_webhook(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    secret: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    settings = get_settings()
    _verify_secret(settings, auth_header=authorization, secret_query=secret)

    raw_body = await request.body()
    try:
        data = orjson.loads(raw_body) if raw_body else {}
    except orjson.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON"
        ) from exc

    payload = WazzupWebhookPayload.model_validate(data)

    if payload.is_test:
        logger.info("wazzup_webhook_test")
        return {"ok": True}

    redis = _redis_from_request(request)
    state = DialogStateStore(
        redis,  # type: ignore[arg-type]
        window=settings.dialog_history_window,
        ttl_seconds=settings.dialog_history_ttl_seconds,
        dedup_ttl_seconds=settings.wazzup_dedup_ttl_seconds,
    )

    accepted = 0
    duplicates = 0
    foreign = 0
    allowed = settings.wazzup_allowed_chat_ids

    if payload.messages:
        for message in payload.messages:
            if not is_chat_allowed(allowed, message.chat_id):
                foreign += 1
                logger.debug(
                    "foreign_chat_dropped_at_webhook",
                    extra={"chat_id": message.chat_id},
                )
                continue
            if not await state.mark_seen(message.message_id):
                duplicates += 1
                continue
            await redis.xadd(
                settings.wazzup_incoming_stream,
                {
                    "kind": "message",
                    "payload": json.dumps(
                        message.model_dump(by_alias=True, mode="json"),
                        ensure_ascii=False,
                    ),
                },
            )
            accepted += 1

    if payload.statuses:
        for stat in payload.statuses:
            await redis.xadd(
                settings.wazzup_incoming_stream,
                {
                    "kind": "status",
                    "payload": json.dumps(
                        stat.model_dump(by_alias=True, mode="json"),
                        ensure_ascii=False,
                    ),
                },
            )

    logger.info(
        "wazzup_webhook_received",
        extra={
            "messages": accepted,
            "duplicates": duplicates,
            "foreign": foreign,
            "statuses": len(payload.statuses or []),
        },
    )
    return {
        "ok": True,
        "accepted": accepted,
        "duplicates": duplicates,
        "foreign": foreign,
    }
