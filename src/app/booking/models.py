"""Strict booking command, result and mock event schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BookingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PrepareBookingCommand(BookingModel):
    conversation_id: UUID
    service_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,31}$")
    slot_start: datetime
    idempotency_key: str = Field(min_length=16, max_length=128)

    @field_validator("slot_start")
    @classmethod
    def require_aware_slot(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("slot_start must be timezone-aware")
        return value


class ConfirmBookingCommand(BookingModel):
    confirmation: Literal["confirm"]
    idempotency_key: str = Field(min_length=16, max_length=128)


class PreparedBooking(BookingModel):
    request_id: UUID
    conversation_id: UUID
    service_id: str
    slot_start: datetime
    slot_end: datetime
    buffer_minutes: int = Field(ge=0)
    status: Literal["ready_for_confirmation"]
    requires_explicit_confirmation: Literal[True] = True
    idempotent_replay: bool = False


class ConfirmedBooking(BookingModel):
    request_id: UUID
    booking_id: UUID
    service_id: str
    slot_start: datetime
    slot_end: datetime
    buffer_minutes: int = Field(ge=0)
    timezone: Literal["Europe/Warsaw"]
    status: Literal["confirmed"]
    calendar_event_ref: str = Field(min_length=1, max_length=256)
    idempotent_replay: bool = False


class CalendarEventCommand(BookingModel):
    idempotency_key: str = Field(min_length=16, max_length=128)
    request_id: UUID
    service_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,31}$")
    start: datetime
    end: datetime
    buffer_minutes: int = Field(ge=0, le=120)

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarEventCommand":
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise ValueError("event interval must be positive and timezone-aware")
        return self


class MockCalendarEvent(BookingModel):
    event_ref: str = Field(pattern=r"^mock-event-[a-f0-9-]{36}$")
    idempotency_key: str
    request_id: UUID
    service_id: str
    start: datetime
    end: datetime
    busy_until: datetime
    status: Literal["confirmed"] = "confirmed"

