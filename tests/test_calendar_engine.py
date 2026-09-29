from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.calendar.adapter import MockGoogleCalendarAdapter
from app.calendar.definition import load_calendar_definition
from app.calendar.engine import AvailabilityEngine
from app.calendar.errors import (
    CalendarUnavailableError,
    InvalidCalendarResponseError,
    InvalidDateError,
    InvalidServiceError,
)
from app.calendar.models import BusyInterval


ROOT = Path(__file__).resolve().parents[1]
WARSAW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=WARSAW)


def make_engine(*, busy=None, unavailable: bool = False) -> AvailabilityEngine:
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    adapter = MockGoogleCalendarAdapter(
        definition.busy_intervals if busy is None else busy,
        unavailable=unavailable,
    )
    return AvailabilityEngine(definition, adapter)


def test_slots_respect_hours_service_duration_buffer_and_busy_time() -> None:
    result = make_engine().available_slots("INTRO_CALL", date(2026, 9, 30), now=NOW)
    starts = {slot.start.strftime("%H:%M") for slot in result.slots}
    assert result.timezone == "Europe/Warsaw"
    assert result.service_duration_minutes == 30
    assert result.buffer_minutes == 15
    assert "09:00" in starts
    assert "09:15" in starts
    assert "09:30" not in starts
    assert "10:45" not in starts
    assert "11:00" in starts
    assert "16:15" in starts
    assert "16:30" not in starts
    assert all((slot.end - slot.start) == timedelta(minutes=30) for slot in result.slots)


def test_weekend_returns_no_slots_and_does_not_query_calendar() -> None:
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    adapter = MockGoogleCalendarAdapter()
    result = AvailabilityEngine(definition, adapter).available_slots("INTRO_CALL", date(2026, 10, 3), now=NOW)
    assert result.slots == ()
    assert adapter.queries == ()


def test_current_day_never_returns_past_slots() -> None:
    result = make_engine(busy=()).available_slots(
        "INTRO_CALL",
        date(2026, 9, 29),
        now=datetime(2026, 9, 29, 12, 7, tzinfo=WARSAW),
    )
    assert result.slots
    assert result.slots[0].start.strftime("%H:%M") == "12:15"


def test_invalid_service_past_date_far_future_and_naive_now_are_rejected() -> None:
    engine = make_engine(busy=())
    with pytest.raises(InvalidServiceError):
        engine.available_slots("VIP_SERVICE", date(2026, 9, 30), now=NOW)
    with pytest.raises(InvalidDateError, match="past"):
        engine.available_slots("INTRO_CALL", date(2026, 9, 28), now=NOW)
    with pytest.raises(InvalidDateError, match="planning horizon"):
        engine.available_slots("INTRO_CALL", date(2027, 1, 1), now=NOW)
    with pytest.raises(InvalidDateError, match="timezone-aware"):
        engine.available_slots("INTRO_CALL", date(2026, 9, 30), now=NOW.replace(tzinfo=None))


def test_calendar_unavailability_fails_closed() -> None:
    with pytest.raises(CalendarUnavailableError):
        make_engine(unavailable=True).available_slots("INTRO_CALL", date(2026, 9, 30), now=NOW)


class InvalidAdapter:
    def get_busy(self, start: datetime, end: datetime):
        return [BusyInterval.model_construct(start=start.replace(tzinfo=None), end=end)]


class ExplodingAdapter:
    def get_busy(self, start: datetime, end: datetime):
        raise RuntimeError("synthetic provider failure")


def test_invalid_or_failed_calendar_response_is_safe() -> None:
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    with pytest.raises(InvalidCalendarResponseError):
        AvailabilityEngine(definition, InvalidAdapter()).available_slots(
            "INTRO_CALL", date(2026, 9, 30), now=NOW
        )
    with pytest.raises(CalendarUnavailableError, match="query failed"):
        AvailabilityEngine(definition, ExplodingAdapter()).available_slots(
            "INTRO_CALL", date(2026, 9, 30), now=NOW
        )

