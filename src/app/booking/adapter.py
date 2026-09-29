"""Atomic, idempotent and network-free mock calendar event adapter."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from uuid import NAMESPACE_URL, uuid5

from app.booking.errors import (
    EventCreationError,
    EventCreationUncertainError,
    IdempotencyConflictError,
    SlotUnavailableError,
)
from app.booking.models import CalendarEventCommand, MockCalendarEvent
from app.calendar.errors import CalendarUnavailableError
from app.calendar.models import BusyInterval


class MockBookingCalendarAdapter:
    """Mock Calendar with atomic overlap checks and idempotent event creation."""

    def __init__(
        self,
        busy_intervals: tuple[BusyInterval, ...] = (),
        *,
        unavailable_on_query: bool = False,
        fail_before_create: bool = False,
        fail_after_create_once: bool = False,
    ) -> None:
        self._initial_busy = busy_intervals
        self._events: dict[str, MockCalendarEvent] = {}
        self._lock = Lock()
        self.unavailable_on_query = unavailable_on_query
        self.fail_before_create = fail_before_create
        self.fail_after_create_once = fail_after_create_once

    def get_busy(self, start: datetime, end: datetime) -> tuple[BusyInterval, ...]:
        if self.unavailable_on_query:
            raise CalendarUnavailableError("mock calendar is unavailable")
        with self._lock:
            created = tuple(
                BusyInterval(start=event.start, end=event.busy_until, label="Synthetic created booking")
                for event in self._events.values()
            )
            combined = (*self._initial_busy, *created)
            return tuple(item for item in combined if item.start < end and item.end > start)

    def find_by_idempotency_key(self, key: str) -> MockCalendarEvent | None:
        with self._lock:
            return self._events.get(key)

    def create_event(self, command: CalendarEventCommand) -> MockCalendarEvent:
        with self._lock:
            existing = self._events.get(command.idempotency_key)
            if existing is not None:
                if (
                    existing.request_id != command.request_id
                    or existing.service_id != command.service_id
                    or existing.start != command.start
                    or existing.end != command.end
                ):
                    raise IdempotencyConflictError("calendar idempotency key was reused for another event")
                return existing
            if self.fail_before_create:
                raise EventCreationError("mock calendar rejected event creation")

            busy_until = command.end + timedelta(minutes=command.buffer_minutes)
            created_busy = tuple(
                BusyInterval(start=event.start, end=event.busy_until, label="Synthetic created booking")
                for event in self._events.values()
            )
            for interval in (*self._initial_busy, *created_busy):
                if command.start < interval.end and busy_until > interval.start:
                    raise SlotUnavailableError("selected slot became unavailable")

            event = MockCalendarEvent(
                event_ref=f"mock-event-{uuid5(NAMESPACE_URL, command.idempotency_key)}",
                idempotency_key=command.idempotency_key,
                request_id=command.request_id,
                service_id=command.service_id,
                start=command.start,
                end=command.end,
                busy_until=busy_until,
            )
            self._events[command.idempotency_key] = event
            if self.fail_after_create_once:
                self.fail_after_create_once = False
                raise EventCreationUncertainError("mock calendar response was lost after creation")
            return event

    @property
    def events(self) -> tuple[MockCalendarEvent, ...]:
        with self._lock:
            return tuple(self._events.values())

