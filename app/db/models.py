"""ORM models for dialogs, messages and leads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Dialog(Base):
    __tablename__ = "dialogs"
    __table_args__ = (Index("ix_dialogs_chat_channel", "chat_id", "channel_id", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    contact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chat_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    human_takeover_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="dialog",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    leads: Mapped[list[Lead]] = relationship(back_populates="dialog")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_dialog_created", "dialog_id", "created_at"),
        Index("ix_messages_wazzup_id", "wazzup_message_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dialog_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dialogs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    wazzup_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    llm_meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
    )

    dialog: Mapped[Dialog] = relationship(back_populates="messages")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dialog_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dialogs.id", ondelete="CASCADE"), nullable=False
    )
    brief: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dialog: Mapped[Dialog] = relationship(back_populates="leads")


class ProcessedMessage(Base):
    """Идемпотентный «штамп» уже принятых вебхуков Wazzup.

    Redis-deduplication защищает от повторов в пределах TTL, но Redis может
    падать или очищаться: если Wazzup ретраит вебхук через сутки, мы всё
    равно не должны прогнать сообщение через LLM второй раз. Поэтому факт
    обработки фиксируется в Postgres с уникальным ключом по
    ``wazzup_message_id``.
    """

    __tablename__ = "processed_messages"

    wazzup_message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
