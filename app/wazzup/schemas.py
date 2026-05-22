"""Pydantic schemas for Wazzup24 v3 webhooks and API responses.

Reference: https://wazzup24.com/help/api-en/webhooks-2/
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

WazzupChatType = Literal[
    "whatsapp",
    "viber",
    "whatsgroup",
    "instagram",
    "telegram",
    "tgapi",
    "avito",
    "vk",
]

WazzupMessageType = Literal[
    "text",
    "image",
    "audio",
    "video",
    "document",
    "vcard",
    "geo",
    "wapi_template",
    "unsupported",
    "missing_call",
    "unknown",
]

WazzupStatus = Literal[
    "sent",
    "delivered",
    "read",
    "error",
    "inbound",
    "edited",
]


class _AllowExtra(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class WazzupContact(_AllowExtra):
    name: str | None = None
    avatar_uri: str | None = Field(default=None, alias="avatarUri")
    username: str | None = None
    phone: str | None = None


class WazzupError(_AllowExtra):
    error: str | None = None
    description: str | None = None


class WazzupMessage(_AllowExtra):
    message_id: str = Field(alias="messageId")
    channel_id: str = Field(alias="channelId")
    chat_type: WazzupChatType | str = Field(alias="chatType")
    chat_id: str = Field(alias="chatId")
    date_time: datetime | None = Field(default=None, alias="dateTime")
    type: WazzupMessageType | str = "text"
    status: WazzupStatus | str | None = None
    text: str | None = None
    content_uri: str | None = Field(default=None, alias="contentUri")
    is_echo: bool = Field(default=False, alias="isEcho")
    author_name: str | None = Field(default=None, alias="authorName")
    author_id: str | None = Field(default=None, alias="authorId")
    contact: WazzupContact | None = None
    error: WazzupError | None = None
    sent_from_app: bool | None = Field(default=None, alias="sentFromApp")
    is_edited: bool | None = Field(default=None, alias="isEdited")
    is_deleted: bool | None = Field(default=None, alias="isDeleted")


class WazzupStatusUpdate(_AllowExtra):
    message_id: str = Field(alias="messageId")
    timestamp: datetime | None = None
    status: WazzupStatus | str
    error: WazzupError | None = None


class WazzupCreateContact(_AllowExtra):
    responsible_user_id: str | None = Field(default=None, alias="responsibleUserId")
    name: str | None = None
    contact_data: list[dict[str, Any]] | None = Field(default=None, alias="contactData")
    source: str | None = None


class WazzupCreateDeal(_AllowExtra):
    responsible_user_id: str | None = Field(default=None, alias="responsibleUserId")
    contacts: list[str] | None = None
    source: str | None = None


class WazzupChannelUpdate(_AllowExtra):
    channel_id: str = Field(alias="channelId")
    state: str
    timestamp: int | None = None


class WazzupWebhookPayload(_AllowExtra):
    test: bool | None = None
    messages: list[WazzupMessage] | None = None
    statuses: list[WazzupStatusUpdate] | None = None
    create_contact: WazzupCreateContact | None = Field(default=None, alias="createContact")
    create_deal: WazzupCreateDeal | None = Field(default=None, alias="createDeal")
    channels_updates: list[WazzupChannelUpdate] | None = Field(
        default=None, alias="channelsUpdates"
    )

    @property
    def is_test(self) -> bool:
        return bool(self.test)


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    channel_id: str = Field(alias="channelId")
    chat_id: str = Field(alias="chatId")
    chat_type: str = Field(alias="chatType")
    text: Annotated[str, Field(min_length=1)]
    cr_m_user_id: str | None = Field(default=None, alias="crmUserId")
