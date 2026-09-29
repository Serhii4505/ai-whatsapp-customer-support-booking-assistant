"""Models for normalized inbound events and mock outbound messages."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WhatsAppModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InboundKind(StrEnum):
    TEXT = "text"
    UNSUPPORTED = "unsupported"


class NormalizedInboundMessage(WhatsAppModel):
    provider_message_id: str = Field(min_length=1, max_length=200)
    sender_id: str = Field(min_length=3, max_length=64)
    timestamp: datetime
    kind: InboundKind
    text: str | None = Field(default=None, max_length=4096)
    original_type: str = Field(min_length=1, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class WebhookBatch(WhatsAppModel):
    messages: tuple[NormalizedInboundMessage, ...] = ()


class WebhookProcessResult(WhatsAppModel):
    ok: bool = True
    received: int = Field(ge=0)
    processed: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    unsupported: int = Field(ge=0)


class MockOutboundMessage(WhatsAppModel):
    recipient_ref: str = Field(min_length=3, max_length=128)
    text: str = Field(min_length=1, max_length=4096)
    queued_at: datetime

