"""initial: dialogs, messages, leads, processed_messages

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-22 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dialogs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("contact_id", sa.String(length=128), nullable=True),
        sa.Column("chat_type", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("human_takeover_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dialogs")),
    )
    op.create_index(
        "ix_dialogs_chat_channel",
        "dialogs",
        ["chat_id", "channel_id"],
        unique=True,
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dialog_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("wazzup_message_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("llm_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["dialog_id"],
            ["dialogs.id"],
            name=op.f("fk_messages_dialog_id_dialogs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(
        "ix_messages_dialog_created", "messages", ["dialog_id", "created_at"]
    )
    op.create_index(
        "ix_messages_wazzup_id", "messages", ["wazzup_message_id"], unique=True
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dialog_id", sa.BigInteger(), nullable=False),
        sa.Column("brief", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dialog_id"],
            ["dialogs.id"],
            name=op.f("fk_leads_dialog_id_dialogs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
    )

    op.create_table(
        "processed_messages",
        sa.Column("wazzup_message_id", sa.String(length=128), nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column("channel_id", sa.String(length=128), nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "wazzup_message_id", name=op.f("pk_processed_messages")
        ),
    )


def downgrade() -> None:
    op.drop_table("processed_messages")
    op.drop_table("leads")
    op.drop_index("ix_messages_wazzup_id", table_name="messages")
    op.drop_index("ix_messages_dialog_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_dialogs_chat_channel", table_name="dialogs")
    op.drop_table("dialogs")
