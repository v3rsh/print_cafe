"""Redis-backed short-term dialog memory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant", "operator"]


@dataclass(slots=True, frozen=True)
class DialogMessage:
    role: Role
    content: str

    def to_json(self) -> str:
        return json.dumps({"role": self.role, "content": self.content}, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> DialogMessage:
        data = json.loads(raw)
        return cls(role=data["role"], content=data["content"])


class _RedisLike(Protocol):
    async def rpush(self, key: str, *values: str) -> int: ...
    async def ltrim(self, key: str, start: int, end: int) -> bool: ...
    async def lrange(self, key: str, start: int, end: int) -> list[bytes | str]: ...
    async def expire(self, key: str, seconds: int) -> bool: ...
    async def delete(self, *keys: str) -> int: ...
    async def set(  # noqa: A003
        self,
        key: str,
        value: str,
        *,
        ex: int | None = ...,
        nx: bool = ...,
    ) -> bool | None: ...
    async def get(self, key: str) -> bytes | str | None: ...


def _decode(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


class DialogStateStore:
    def __init__(
        self,
        redis: _RedisLike,
        *,
        window: int = 20,
        ttl_seconds: int = 7 * 24 * 3600,
        dedup_ttl_seconds: int = 24 * 3600,
        outgoing_sent_ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis
        self._window = window
        self._ttl = ttl_seconds
        self._dedup_ttl = dedup_ttl_seconds
        self._outgoing_sent_ttl = outgoing_sent_ttl_seconds

    @staticmethod
    def _messages_key(chat_id: str) -> str:
        return f"dialog:{chat_id}:messages"

    @staticmethod
    def _takeover_key(chat_id: str) -> str:
        return f"dialog:{chat_id}:human_takeover"

    @staticmethod
    def _dedup_key(message_id: str) -> str:
        return f"wazzup:dedup:{message_id}"

    @staticmethod
    def _outgoing_sent_key(message_id: str) -> str:
        return f"outgoing:sent:{message_id}"

    async def append_message(self, chat_id: str, message: DialogMessage) -> None:
        key = self._messages_key(chat_id)
        await self._redis.rpush(key, message.to_json())
        await self._redis.ltrim(key, -self._window, -1)
        await self._redis.expire(key, self._ttl)

    async def get_history(self, chat_id: str) -> list[DialogMessage]:
        raw = await self._redis.lrange(self._messages_key(chat_id), 0, -1)
        return [DialogMessage.from_json(_decode(item)) for item in raw]

    async def clear_history(self, chat_id: str) -> None:
        await self._redis.delete(self._messages_key(chat_id))

    async def set_human_takeover(self, chat_id: str) -> None:
        await self._redis.set(self._takeover_key(chat_id), "1", ex=self._ttl)

    async def clear_human_takeover(self, chat_id: str) -> None:
        await self._redis.delete(self._takeover_key(chat_id))

    async def is_human_takeover(self, chat_id: str) -> bool:
        value = await self._redis.get(self._takeover_key(chat_id))
        return value is not None

    async def mark_seen(self, message_id: str) -> bool:
        result = await self._redis.set(
            self._dedup_key(message_id),
            "1",
            ex=self._dedup_ttl,
            nx=True,
        )
        return bool(result)

    async def mark_outgoing_sent(self, message_id: str, *, ttl: int | None = None) -> None:
        """Помечаем messageId как отправленный нами, чтобы потом распознать собственное echo."""
        await self._redis.set(
            self._outgoing_sent_key(message_id),
            "1",
            ex=ttl if ttl is not None else self._outgoing_sent_ttl,
        )

    async def is_our_outgoing(self, message_id: str) -> bool:
        """True если этот messageId недавно отправлен нами через WazzupClient.send_message."""
        value = await self._redis.get(self._outgoing_sent_key(message_id))
        return value is not None
