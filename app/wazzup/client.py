"""Async HTTP client for Wazzup24 v3 API."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, Self

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.wazzup.schemas import SendMessageRequest

logger = logging.getLogger(__name__)


class WazzupClientError(RuntimeError):
    """Raised on non-recoverable failures from Wazzup API."""


_RETRY_STATUSES = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUSES
    return isinstance(exc, httpx.TransportError | httpx.TimeoutException)


class WazzupClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.wazzup24.com",
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                retry=retry_if_exception_type(
                    (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.request(method, path, **kwargs)
                    if response.status_code in _RETRY_STATUSES:
                        response.raise_for_status()
                    return response
        except RetryError as exc:
            raise WazzupClientError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            if _is_retryable(exc):
                raise WazzupClientError(str(exc)) from exc
            return exc.response
        raise WazzupClientError("Unreachable retry loop")

    async def send_message(
        self,
        *,
        channel_id: str,
        chat_id: str,
        chat_type: str,
        text: str,
        crm_user_id: str | None = None,
    ) -> dict[str, Any]:
        payload = SendMessageRequest.model_validate(
            {
                "channelId": channel_id,
                "chatId": chat_id,
                "chatType": chat_type,
                "text": text,
                "crmUserId": crm_user_id,
            }
        ).model_dump(by_alias=True, exclude_none=True)

        response = await self._request("POST", "/v3/message", json=payload)
        if response.status_code >= 400:
            logger.warning(
                "wazzup_send_message_failed",
                extra={
                    "status": response.status_code,
                    "body": response.text,
                    "chat_id": chat_id,
                    "channel_id": channel_id,
                },
            )
            raise WazzupClientError(f"send_message failed: {response.status_code} {response.text}")
        result: dict[str, Any] = response.json() if response.content else {}
        return result

    async def add_tag(self, *, chat_id: str, tag: str) -> None:
        """Best-effort tag add. TODO: confirm exact contract on real account."""
        try:
            response = await self._request(
                "POST",
                f"/v3/chats/{chat_id}/tags",
                json={"tag": tag},
            )
        except WazzupClientError as exc:
            logger.warning("wazzup_add_tag_unavailable", extra={"error": str(exc)})
            return

        if response.status_code >= 400:
            logger.info(
                "wazzup_add_tag_unsupported",
                extra={"status": response.status_code, "body": response.text, "tag": tag},
            )

    async def set_webhook(
        self,
        webhook_url: str,
        *,
        messages_and_statuses: bool = True,
        contacts_and_deals_creation: bool = False,
        channels_updates: bool = False,
        template_status: bool = False,
    ) -> dict[str, Any]:
        body = {
            "webhooksUri": webhook_url,
            "subscriptions": {
                "messagesAndStatuses": messages_and_statuses,
                "contactsAndDealsCreation": contacts_and_deals_creation,
                "channelsUpdates": channels_updates,
                "templateStatus": template_status,
            },
        }
        response = await self._request("PATCH", "/v3/webhooks", json=body)
        if response.status_code >= 400:
            raise WazzupClientError(f"set_webhook failed: {response.status_code} {response.text}")
        result: dict[str, Any] = response.json() if response.content else {}
        return result

    async def get_webhook(self) -> dict[str, Any]:
        response = await self._request("GET", "/v3/webhooks")
        if response.status_code >= 400:
            raise WazzupClientError(f"get_webhook failed: {response.status_code} {response.text}")
        result: dict[str, Any] = response.json()
        return result
