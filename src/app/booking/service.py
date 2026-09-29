"""Booking state machine with explicit confirmation and final availability recheck."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from app.booking.adapter import MockBookingCalendarAdapter
from app.booking.errors import EventCreationError, SlotUnavailableError
from app.booking.models import (
    CalendarEventCommand,
    ConfirmBookingCommand,
    ConfirmedBooking,
    PrepareBookingCommand,
    PreparedBooking,
)
from app.booking.repository import BookingRepository
from app.calendar.engine import AvailabilityEngine
from app.calendar.errors import CalendarUnavailableError
from app.calendar.timezone import strict_local_datetime


class BookingService:
    def __init__(
        self,
        repository: BookingRepository,
        availability: AvailabilityEngine,
        calendar: MockBookingCalendarAdapter,
    ) -> None:
        self.repository = repository
        self.availability = availability
        self.calendar = calendar
        self.zone = ZoneInfo("Europe/Warsaw")

    @staticmethod
    def _hash(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def prepare(
        self,
        command: PrepareBookingCommand,
        *,
        now: datetime | None = None,
    ) -> PreparedBooking:
        local_now = self._local_now(now)
        local_start = command.slot_start.astimezone(self.zone)
        # Reject DST gaps/folds and offset tricks by reconstructing the local wall time.
        strict_start = strict_local_datetime(local_start.date(), local_start.time().replace(tzinfo=None), self.zone)
        if strict_start != local_start:
            raise SlotUnavailableError("slot_start does not represent a valid Europe/Warsaw local time")
        availability = self.availability.available_slots(
            command.service_id,
            local_start.date(),
            now=local_now,
        )
        selected = next((slot for slot in availability.slots if slot.start == local_start), None)
        if selected is None:
            raise SlotUnavailableError("selected slot is not currently available")
        normalized = command.model_copy(update={"slot_start": local_start})
        request_hash = self._hash(
            {
                "conversation_id": str(normalized.conversation_id),
                "service_id": normalized.service_id,
                "slot_start": normalized.slot_start.isoformat(),
            }
        )
        return self.repository.prepare(
            normalized,
            selected.end,
            availability.buffer_minutes,
            request_hash,
            local_now,
        )

    def confirm(
        self,
        request_id: UUID,
        command: ConfirmBookingCommand,
        *,
        now: datetime | None = None,
    ) -> ConfirmedBooking:
        local_now = self._local_now(now)
        request_hash = self._hash(
            {"request_id": str(request_id), "confirmation": command.confirmation}
        )
        state = self.repository.begin_confirmation(
            request_id,
            command.idempotency_key,
            request_hash,
            local_now,
        )
        if state.replay is not None:
            return state.replay

        event_command = CalendarEventCommand(
            idempotency_key=state.event_idempotency_key,
            request_id=state.request_id,
            service_id=state.service_id,
            start=state.slot_start,
            end=state.slot_end,
            buffer_minutes=state.buffer_minutes,
        )

        # Recover safely if the previous attempt created the event but lost its response.
        existing_event = self.calendar.find_by_idempotency_key(state.event_idempotency_key)
        if existing_event is not None:
            return self.repository.finalize(
                state,
                command.idempotency_key,
                request_hash,
                existing_event.event_ref,
                local_now,
                recovered=True,
            )

        try:
            current = self.availability.available_slots(
                state.service_id,
                state.slot_start.astimezone(self.zone).date(),
                now=local_now,
            )
        except CalendarUnavailableError:
            self.repository.mark_failed(state.booking_id, "booking.calendar_unavailable", local_now)
            raise
        if not any(slot.start == state.slot_start and slot.end == state.slot_end for slot in current.slots):
            self.repository.mark_failed(state.booking_id, "booking.slot_unavailable", local_now)
            raise SlotUnavailableError("selected slot became unavailable before confirmation")

        try:
            event = self.calendar.create_event(event_command)
        except SlotUnavailableError:
            self.repository.mark_failed(state.booking_id, "booking.slot_conflict", local_now)
            raise
        except EventCreationError:
            self.repository.mark_failed(state.booking_id, "booking.event_creation_failed", local_now)
            raise

        return self.repository.finalize(
            state,
            command.idempotency_key,
            request_hash,
            event.event_ref,
            local_now,
        )

    def _local_now(self, now: datetime | None) -> datetime:
        resolved = now or datetime.now(self.zone)
        if resolved.tzinfo is None or resolved.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return resolved.astimezone(self.zone)

