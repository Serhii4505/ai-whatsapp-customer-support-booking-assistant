"""Strict models for demo calendar configuration and availability results."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CalendarModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BusyInterval(CalendarModel):
    start: datetime
    end: datetime
    label: str = Field(default="Synthetic busy interval", min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_interval(self) -> "BusyInterval":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("busy interval timestamps must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("busy interval end must be after start")
        return self


class CalendarDefinition(CalendarModel):
    calendar_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    company: str = Field(min_length=1, max_length=120)
    timezone: str = Field(min_length=1, max_length=64)
    approved: bool
    working_days: tuple[int, ...] = Field(min_length=1, max_length=7)
    opens_at: time
    closes_at: time
    slot_interval_minutes: int = Field(ge=5, le=60, multiple_of=5)
    max_days_ahead: int = Field(ge=1, le=365)
    busy_intervals: tuple[BusyInterval, ...] = ()

    @field_validator("working_days")
    @classmethod
    def validate_working_days(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) != len(value) or any(day < 0 or day > 6 for day in value):
            raise ValueError("working_days must contain unique weekday numbers from 0 to 6")
        return value

    @model_validator(mode="after")
    def validate_definition(self) -> "CalendarDefinition":
        if not self.approved:
            raise ValueError("calendar definition must be approved")
        if self.opens_at.tzinfo is not None or self.closes_at.tzinfo is not None:
            raise ValueError("working-hour values must be local wall times")
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be after opens_at")
        return self


class AvailableSlot(CalendarModel):
    service_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,31}$")
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_slot(self) -> "AvailableSlot":
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise ValueError("slot must be a positive timezone-aware interval")
        return self


class AvailabilityResponse(CalendarModel):
    calendar_id: str
    service_id: str
    date: date
    timezone: str
    service_duration_minutes: int = Field(gt=0)
    buffer_minutes: int = Field(ge=0)
    slots: tuple[AvailableSlot, ...]
    source: str = "mock_calendar"

