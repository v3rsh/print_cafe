"""YandexGPT client over the OpenAI-compatible AI Studio endpoint.

YandexGPT 5.1 Pro is exposed via an OpenAI-compatible endpoint at
``https://llm.api.cloud.yandex.net/v1`` (Yandex AI Studio, since 2026-03).
Authentication uses an API key of a service account with the
``ai.languageModels.user`` role. Custom headers ``x-folder-id`` and
``x-data-logging-enabled`` are mandatory. Model id is the Yandex URI like
``gpt://<folder_id>/yandexgpt/rc`` (5.1 Pro release-candidate branch).
"""

from __future__ import annotations

import logging
from typing import Any, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

logger = logging.getLogger(__name__)


class YandexGPTClient:
    def __init__(
        self,
        *,
        api_key: str,
        folder_id: str,
        model: str,
        base_url: str = "https://llm.api.cloud.yandex.net/v1",
        temperature: float = 0.3,
        max_tokens: int = 800,
        data_logging_enabled: bool = False,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("YANDEX_API_KEY is empty")
        if not folder_id:
            raise ValueError("YANDEX_FOLDER_ID is empty")

        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "x-folder-id": folder_id,
                "x-data-logging-enabled": "true" if data_logging_enabled else "false",
            },
        )

    @property
    def model(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=cast("list[ChatCompletionMessageParam]", messages),
            temperature=temperature if temperature is not None else self._temperature,
            max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
        )
        choice = completion.choices[0]
        text = choice.message.content or ""
        logger.debug(
            "yandex_chat_completion",
            extra={
                "model": self._model,
                "finish_reason": choice.finish_reason,
                "usage": completion.usage.model_dump() if completion.usage else None,
            },
        )
        return text

    async def aclose(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> YandexGPTClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
