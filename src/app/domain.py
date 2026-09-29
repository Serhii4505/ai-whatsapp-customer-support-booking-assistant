"""Strict domain models and state enums used across the assistant."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


class IntegrationMode(StrEnum):
    MOCK = "mock"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    AWAITING_DETAILS = "awaiting_details"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    HANDED_OFF = "handed_off"
    CLOSED = "closed"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    REJECTED = "rejected"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class BookingRequestStatus(StrEnum):
    COLLECTING = "collecting"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class BookingStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AuditActor(StrEnum):
    SYSTEM = "system"
    CUSTOMER = "customer"
    MANAGER = "manager"


class DemoService(StrictModel):
    service_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,31}$")
    name: str = Field(min_length=2, max_length=80)
    duration_minutes: int = Field(ge=15, le=240, multiple_of=15)
    buffer_minutes: int = Field(default=15, ge=0, le=120, multiple_of=5)
    active: bool = True


class Contact(StrictModel):
    contact_id: UUID = Field(default_factory=uuid4)
    display_name: str = Field(min_length=1, max_length=100)
    external_user_ref: str = Field(min_length=8, max_length=128)
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")
    opt_in_recorded: bool = False
    created_at: datetime


class Conversation(StrictModel):
    conversation_id: UUID = Field(default_factory=uuid4)
    contact_id: UUID
    status: ConversationStatus = ConversationStatus.ACTIVE
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")
    handed_off: bool = False
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_handoff_state(self) -> "Conversation":
        if self.status == ConversationStatus.HANDED_OFF and not self.handed_off:
            raise ValueError("handed_off must be true for handed_off status")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class Message(StrictModel):
    message_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    provider_message_id: str = Field(min_length=1, max_length=200)
    direction: MessageDirection
    status: MessageStatus
    text: str = Field(min_length=1, max_length=4096)
    received_at: datetime


class BookingRequest(StrictModel):
    request_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    service_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,31}$")
    requested_start: datetime
    requested_end: datetime
    status: BookingRequestStatus = BookingRequestStatus.COLLECTING
    customer_confirmed: bool = False
    expires_at: datetime

    @model_validator(mode="after")
    def validate_time_and_confirmation(self) -> "BookingRequest":
        if self.requested_start.tzinfo is None or self.requested_end.tzinfo is None:
            raise ValueError("booking timestamps must be timezone-aware")
        if self.requested_end <= self.requested_start:
            raise ValueError("requested_end must be after requested_start")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if self.status == BookingRequestStatus.CONFIRMED and not self.customer_confirmed:
            raise ValueError("confirmed request requires explicit customer confirmation")
        return self


class Booking(StrictModel):
    booking_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128)
    calendar_event_ref: str | None = Field(default=None, max_length=256)
    status: BookingStatus = BookingStatus.PENDING
    created_at: datetime

    @model_validator(mode="after")
    def validate_confirmed_event(self) -> "Booking":
        if self.status == BookingStatus.CONFIRMED and not self.calendar_event_ref:
            raise ValueError("confirmed booking requires a calendar event reference")
        return self


class KnowledgeSource(StrictModel):
    source_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    checksum_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: bool = False
    created_at: datetime


class KnowledgeChunk(StrictModel):
    chunk_id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    content: str = Field(min_length=1, max_length=8000)
    ordinal: int = Field(ge=0)


class IdempotencyRecord(StrictModel):
    key: str = Field(min_length=16, max_length=128)
    operation: str = Field(min_length=1, max_length=64)
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_json: dict[str, Any] | None = None
    created_at: datetime


class AuditEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,63}$")
    actor: AuditActor = AuditActor.SYSTEM
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class HealthResponse(StrictModel):
    status: str
    service: str
    version: str
    environment: str
    database: str
    company: str
    timezone: str
    integrations: dict[str, str]
    data_policy: str


DEMO_SERVICES = (
    DemoService(service_id="INTRO_CALL", name="Introductory Consultation", duration_minutes=30),
    DemoService(service_id="STANDARD_VISIT", name="Standard Service Appointment", duration_minutes=60),
    DemoService(service_id="EXTENDED_SESSION", name="Extended Service Session", duration_minutes=90),
)
