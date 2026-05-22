"""Инструменты, которые агент может вызывать."""

from app.tools.handoff import (
    HANDOFF_TOOL_SCHEMA,
    HandoffResult,
    execute_handoff,
)

__all__ = [
    "HANDOFF_TOOL_SCHEMA",
    "HandoffResult",
    "execute_handoff",
]
