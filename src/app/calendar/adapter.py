"""Read-only calendar adapter contract and deterministic mock implementation."""

from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Protocol, Sequence

from app.calendar.errors import CalendarUnavailableError
from app.calendar.models import BusyInterval, CalendarDefinition


class CalendarAvailabilityAdapter(Protocol):
    def get_busy(self, start: datetime, end: datetime) -> Sequence[BusyInterval]:
        """Return busy intervals. The Phase 4 interface exposes no write method."""


class MockGoogleCalendarAdapter:
    """Network-free, read-only calendar adapter with deterministic busy data."""

    def __init__(self, busy_intervals: Sequence[BusyInterval] = (), *, unavailable: bool = False) -> None:
        self._busy_intervals = tuple(busy_intervals)
        self._unavailable = unavailable
        self._lock = Lock()
        self._queries: list[tuple[datetime, datetime]] = []

    @classmethod
    def from_definition(cls, definition: CalendarDefinition) -> "MockGoogleCalendarAdapter":
        return cls(definition.busy_intervals)

    def get_busy(self, start: datetime, end: datetime) -> tuple[BusyInterval, ...]:
        if self._unavailable:
            raise CalendarUnavailableError("mock calendar is unavailable")
        with self._lock:
            self._queries.append((start, end))
        return tuple(item for item in self._busy_intervals if item.start < end and item.end > start)

    @property
    def queries(self) -> tuple[tuple[datetime, datetime], ...]:
        with self._lock:
            return tuple(self._queries)

