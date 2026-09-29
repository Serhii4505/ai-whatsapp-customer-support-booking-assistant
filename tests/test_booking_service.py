import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.booking.adapter import MockBookingCalendarAdapter
from app.booking.errors import (
    EventCreationError,
    EventCreationUncertainError,
    IdempotencyConflictError,
    InvalidBookingStateError,
    SlotUnavailableError,
)
from app.booking.models import ConfirmBookingCommand, PrepareBookingCommand
from app.booking.repository import BookingRepository
from app.booking.service import BookingService
from app.calendar.definition import load_calendar_definition
from app.calendar.engine import AvailabilityEngine
from app.calendar.errors import CalendarUnavailableError
from app.database import initialize_database


ROOT = Path(__file__).resolve().parents[1]
WARSAW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=WARSAW)
SLOT = datetime(2026, 9, 30, 9, 0, tzinfo=WARSAW)


def build_service(
    tmp_path: Path,
    *,
    adapter: MockBookingCalendarAdapter | None = None,
    conversation_id: UUID | None = None,
) -> tuple[BookingService, MockBookingCalendarAdapter, UUID, Path]:
    database_path = tmp_path / "assistant.sqlite3"
    initialize_database(database_path)
    conversation_id = conversation_id or uuid4()
    contact_id = uuid4()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO contacts VALUES (?, 'Synthetic Customer', ?, 'en', 1, ?)",
            (str(contact_id), f"synthetic-{contact_id}", NOW.isoformat()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO conversations VALUES (?, ?, 'active', 'en', 0, ?, ?)",
            (str(conversation_id), str(contact_id), NOW.isoformat(), NOW.isoformat()),
        )
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    calendar = adapter or MockBookingCalendarAdapter(definition.busy_intervals)
    engine = AvailabilityEngine(definition, calendar)
    service = BookingService(BookingRepository(database_path), engine, calendar)
    return service, calendar, conversation_id, database_path


def prepare(service: BookingService, conversation_id: UUID, *, key: str = "prepare-key-00000001", slot=SLOT):
    return service.prepare(
        PrepareBookingCommand(
            conversation_id=conversation_id,
            service_id="INTRO_CALL",
            slot_start=slot,
            idempotency_key=key,
        ),
        now=NOW,
    )


def confirm(service: BookingService, request_id: UUID, *, key: str = "confirm-key-00000001"):
    return service.confirm(
        request_id,
        ConfirmBookingCommand(confirmation="confirm", idempotency_key=key),
        now=NOW,
    )


def test_prepare_requires_explicit_later_confirmation_and_persists_state(tmp_path: Path) -> None:
    service, calendar, conversation_id, database_path = build_service(tmp_path)
    result = prepare(service, conversation_id)
    assert result.status == "ready_for_confirmation"
    assert result.requires_explicit_confirmation is True
    assert result.slot_end - result.slot_start == timedelta(minutes=30)
    assert result.buffer_minutes == 15
    assert calendar.events == ()
    with sqlite3.connect(database_path) as connection:
        stored = connection.execute(
            "SELECT status, customer_confirmed FROM booking_requests WHERE request_id = ?",
            (str(result.request_id),),
        ).fetchone()
    assert stored == ("ready_for_confirmation", 0)


def test_explicit_confirmation_rechecks_and_creates_once(tmp_path: Path) -> None:
    service, calendar, conversation_id, database_path = build_service(tmp_path)
    prepared = prepare(service, conversation_id)
    first = confirm(service, prepared.request_id)
    replay = confirm(service, prepared.request_id)
    another_key = confirm(service, prepared.request_id, key="confirm-key-00000002")

    assert first.status == "confirmed"
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert another_key.idempotent_replay is True
    assert first.calendar_event_ref == replay.calendar_event_ref == another_key.calendar_event_ref
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.start.tzinfo == WARSAW
    assert event.end - event.start == timedelta(minutes=30)
    assert event.busy_until - event.end == timedelta(minutes=15)

    with sqlite3.connect(database_path) as connection:
        request_row = connection.execute(
            "SELECT status, customer_confirmed FROM booking_requests WHERE request_id = ?",
            (str(prepared.request_id),),
        ).fetchone()
        booking_count = connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        confirmed_events = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'booking.confirmed'"
        ).fetchone()[0]
    assert request_row == ("confirmed", 1)
    assert booking_count == 1
    assert confirmed_events == 1


def test_prepare_is_idempotent_and_key_reuse_conflict_is_rejected(tmp_path: Path) -> None:
    service, _, conversation_id, _ = build_service(tmp_path)
    first = prepare(service, conversation_id)
    replay = prepare(service, conversation_id)
    assert replay.request_id == first.request_id
    assert replay.idempotent_replay is True
    with pytest.raises(IdempotencyConflictError):
        prepare(
            service,
            conversation_id,
            key="prepare-key-00000001",
            slot=datetime(2026, 9, 30, 9, 15, tzinfo=WARSAW),
        )


def test_double_booking_is_blocked_after_final_recheck(tmp_path: Path) -> None:
    database_path = tmp_path / "assistant.sqlite3"
    initialize_database(database_path)
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    calendar = MockBookingCalendarAdapter(definition.busy_intervals)
    engine = AvailabilityEngine(definition, calendar)
    repository = BookingRepository(database_path)
    service = BookingService(repository, engine, calendar)
    conversations = [uuid4(), uuid4()]
    with sqlite3.connect(database_path) as connection:
        for index, conversation_id in enumerate(conversations):
            contact_id = uuid4()
            connection.execute(
                "INSERT INTO contacts VALUES (?, ?, ?, 'en', 1, ?)",
                (str(contact_id), f"Synthetic {index}", f"synthetic-{index}", NOW.isoformat()),
            )
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, 'active', 'en', 0, ?, ?)",
                (str(conversation_id), str(contact_id), NOW.isoformat(), NOW.isoformat()),
            )
    request_a = prepare(service, conversations[0], key="prepare-key-00000011")
    request_b = prepare(service, conversations[1], key="prepare-key-00000012")
    confirm(service, request_a.request_id, key="confirm-key-00000011")
    with pytest.raises(SlotUnavailableError):
        confirm(service, request_b.request_id, key="confirm-key-00000012")
    assert len(calendar.events) == 1


def test_calendar_unavailable_and_creation_failure_are_persisted(tmp_path: Path) -> None:
    service, calendar, conversation_id, database_path = build_service(tmp_path)
    prepared = prepare(service, conversation_id)
    calendar.unavailable_on_query = True
    with pytest.raises(CalendarUnavailableError, match="unavailable"):
        confirm(service, prepared.request_id)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT status FROM bookings").fetchone()[0] == "failed"
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'booking.calendar_unavailable'"
        ).fetchone()[0] == 1

    service2, calendar2, conversation2, database2 = build_service(tmp_path / "second")
    prepared2 = prepare(service2, conversation2, key="prepare-key-00000021")
    calendar2.fail_before_create = True
    with pytest.raises(EventCreationError):
        confirm(service2, prepared2.request_id, key="confirm-key-00000021")
    with sqlite3.connect(database2) as connection:
        assert connection.execute("SELECT status FROM bookings").fetchone()[0] == "failed"


def test_lost_create_response_is_recovered_without_second_event(tmp_path: Path) -> None:
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    adapter = MockBookingCalendarAdapter(definition.busy_intervals, fail_after_create_once=True)
    service, calendar, conversation_id, database_path = build_service(tmp_path, adapter=adapter)
    prepared = prepare(service, conversation_id)
    with pytest.raises(EventCreationUncertainError):
        confirm(service, prepared.request_id)
    assert len(calendar.events) == 1

    recovered = confirm(service, prepared.request_id)
    assert recovered.status == "confirmed"
    assert recovered.idempotent_replay is True
    assert len(calendar.events) == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT status FROM bookings").fetchone()[0] == "confirmed"
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'booking.confirmed_recovered'"
        ).fetchone()[0] == 1


def test_expired_request_and_invalid_confirmation_are_rejected(tmp_path: Path) -> None:
    service, _, conversation_id, database_path = build_service(tmp_path)
    prepared = prepare(service, conversation_id)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE booking_requests SET expires_at = ? WHERE request_id = ?",
            ((NOW - timedelta(minutes=1)).isoformat(), str(prepared.request_id)),
        )
    with pytest.raises(InvalidBookingStateError, match="expired"):
        confirm(service, prepared.request_id)
    with pytest.raises(ValidationError):
        ConfirmBookingCommand.model_validate(
            {"confirmation": "yes", "idempotency_key": "confirm-key-00000031"}
        )
