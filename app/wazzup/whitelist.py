"""Shared whitelist helpers for Wazzup chat identifiers.

This module is the single source of truth for whitelist checks. It is used by
the webhook (the earliest gate, before any data hits Redis Stream) and by the
worker (defence-in-depth, before any DB writes happen).
"""

from __future__ import annotations

from collections.abc import Iterable


def normalize_chat_id(chat_id: str) -> str:
    """Strip ``+`` / whitespace so Wazzup ids match config values byte-for-byte."""
    return chat_id.replace("+", "").replace(" ", "").strip()


def is_chat_allowed(allowed: Iterable[str], chat_id: str) -> bool:
    """Return True when ``chat_id`` is allowed.

    Empty whitelist is treated as "allow everything" for backwards compatibility
    in local/dev setups. The production deployment **must** set
    ``WAZZUP_ALLOWED_CHAT_IDS`` to avoid leaking other companies' chats.
    """
    allowed_list = [item for item in allowed if item]
    if not allowed_list:
        return True
    normalized = {normalize_chat_id(item) for item in allowed_list}
    return normalize_chat_id(chat_id) in normalized
