"""SQLite persistence and audit log for the booking state machine."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.booking.errors import (
    BookingRequestNotFoundError,
    ConversationNotFoundError,
    IdempotencyConflictError,
    InvalidBookingStateError,
)
from app.booking.models import ConfirmedBooking, PrepareBookingCommand, PreparedBooking
from app.domain import DEMO_SERVICES


WARSAW = ZoneInfo("Europe/Warsaw")


@dataclass(frozen=True)
class ConfirmationState:
    request_id: UUID
    booking_id: UUID
    event_idempotency_key: str
    service_id: str
    slot_start: datetime
    slot_end: datetime
    buffer_minutes: int
    replay: ConfirmedBooking | None = None


class BookingRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        event_type: str,
        entity_type: str,
        entity_id: str,
        created_at: datetime,
        payload: dict[str, object] | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO audit_events "
            "(event_id, event_type, actor, entity_type, entity_id, payload_json, created_at) "
            "VALUES (?, ?, 'customer', ?, ?, ?, ?)",
            (
                str(uuid4()),
                event_type,
                entity_type,
                entity_id,
                json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
                created_at.isoformat(),
            ),
        )

    @staticmethod
    def _existing_idempotency(
        connection: sqlite3.Connection,
        key: str,
        operation: str,
        request_hash: str,
    ) -> str | None:
        row = connection.execute(
            "SELECT operation, request_hash, response_json FROM idempotency_keys WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation or row["request_hash"] != request_hash:
            raise IdempotencyConflictError("idempotency key was reused for a different operation or payload")
        return row["response_json"]

    def prepare(
        self,
        command: PrepareBookingCommand,
        slot_end: datetime,
        buffer_minutes: int,
        request_hash: str,
        now: datetime,
    ) -> PreparedBooking:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._existing_idempotency(
                connection, command.idempotency_key, "prepare_booking", request_hash
            )
            if existing is not None:
                connection.commit()
                return PreparedBooking.model_validate_json(existing).model_copy(
                    update={"idempotent_replay": True}
                )
            conversation = connection.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?",
                (str(command.conversation_id),),
            ).fetchone()
            if conversation is None:
                connection.rollback()
                raise ConversationNotFoundError("conversation does not exist")

            request_id = uuid4()
            expires_at = now + timedelta(minutes=15)
            connection.execute(
                "INSERT INTO booking_requests "
                "(request_id, conversation_id, service_id, requested_start, requested_end, status, "
                "customer_confirmed, expires_at) VALUES (?, ?, ?, ?, ?, 'ready_for_confirmation', 0, ?)",
                (
                    str(request_id),
                    str(command.conversation_id),
                    command.service_id,
                    command.slot_start.isoformat(),
                    slot_end.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            result = PreparedBooking(
                request_id=request_id,
                conversation_id=command.conversation_id,
                service_id=command.service_id,
                slot_start=command.slot_start,
                slot_end=slot_end,
                buffer_minutes=buffer_minutes,
                status="ready_for_confirmation",
            )
            self._audit(
                connection,
                "booking.prepared",
                "booking_request",
                str(request_id),
                now,
                {"service_id": command.service_id},
            )
            connection.execute(
                "INSERT INTO idempotency_keys(key, operation, request_hash, response_json, created_at) "
                "VALUES (?, 'prepare_booking', ?, ?, ?)",
                (command.idempotency_key, request_hash, result.model_dump_json(), now.isoformat()),
            )
            connection.commit()
            return result

    def begin_confirmation(
        self,
        request_id: UUID,
        confirmation_key: str,
        request_hash: str,
        now: datetime,
    ) -> ConfirmationState:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_result = self._existing_idempotency(
                connection, confirmation_key, "confirm_booking", request_hash
            )
            if existing_result is not None:
                connection.commit()
                replay = ConfirmedBooking.model_validate_json(existing_result).model_copy(
                    update={"idempotent_replay": True}
                )
                return ConfirmationState(
                    request_id=replay.request_id,
                    booking_id=replay.booking_id,
                    event_idempotency_key=confirmation_key,
                    service_id=replay.service_id,
                    slot_start=replay.slot_start,
                    slot_end=replay.slot_end,
                    buffer_minutes=replay.buffer_minutes,
                    replay=replay,
                )

            request_row = connection.execute(
                "SELECT * FROM booking_requests WHERE request_id = ?", (str(request_id),)
            ).fetchone()
            if request_row is None:
                connection.rollback()
                raise BookingRequestNotFoundError("booking request does not exist")

            booking_row = connection.execute(
                "SELECT * FROM bookings WHERE request_id = ?", (str(request_id),)
            ).fetchone()
            if request_row["status"] == "confirmed" and booking_row is not None:
                result = self._confirmed_from_rows(request_row, booking_row, replay=True)
                connection.execute(
                    "INSERT INTO idempotency_keys(key, operation, request_hash, response_json, created_at) "
                    "VALUES (?, 'confirm_booking', ?, ?, ?)",
                    (confirmation_key, request_hash, result.model_dump_json(), now.isoformat()),
                )
                connection.commit()
                return ConfirmationState(
                    request_id=request_id,
                    booking_id=result.booking_id,
                    event_idempotency_key=booking_row["idempotency_key"],
                    service_id=result.service_id,
                    slot_start=result.slot_start,
                    slot_end=result.slot_end,
                    buffer_minutes=result.buffer_minutes,
                    replay=result,
                )

            if request_row["status"] != "ready_for_confirmation":
                connection.rollback()
                raise InvalidBookingStateError("booking request cannot be confirmed from its current state")
            expires_at = datetime.fromisoformat(request_row["expires_at"])
            if expires_at <= now:
                connection.execute(
                    "UPDATE booking_requests SET status = 'expired' WHERE request_id = ?",
                    (str(request_id),),
                )
                self._audit(connection, "booking.expired", "booking_request", str(request_id), now)
                connection.commit()
                raise InvalidBookingStateError("booking confirmation window has expired")

            service = next(item for item in DEMO_SERVICES if item.service_id == request_row["service_id"])
            if booking_row is None:
                booking_id = uuid4()
                event_key = confirmation_key
                connection.execute(
                    "INSERT INTO bookings "
                    "(booking_id, request_id, idempotency_key, calendar_event_ref, status, created_at) "
                    "VALUES (?, ?, ?, NULL, 'pending', ?)",
                    (str(booking_id), str(request_id), event_key, now.isoformat()),
                )
                self._audit(connection, "booking.confirmation_started", "booking", str(booking_id), now)
            else:
                booking_id = UUID(booking_row["booking_id"])
                event_key = booking_row["idempotency_key"]
                connection.execute(
                    "UPDATE bookings SET status = 'pending' WHERE booking_id = ?",
                    (str(booking_id),),
                )
                self._audit(connection, "booking.confirmation_retried", "booking", str(booking_id), now)
            connection.commit()
            return ConfirmationState(
                request_id=request_id,
                booking_id=booking_id,
                event_idempotency_key=event_key,
                service_id=request_row["service_id"],
                slot_start=datetime.fromisoformat(request_row["requested_start"]).astimezone(WARSAW),
                slot_end=datetime.fromisoformat(request_row["requested_end"]).astimezone(WARSAW),
                buffer_minutes=service.buffer_minutes,
            )

    def mark_failed(self, booking_id: UUID, event_type: str, now: datetime) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE bookings SET status = 'failed' WHERE booking_id = ? AND status != 'confirmed'",
                (str(booking_id),),
            )
            self._audit(connection, event_type, "booking", str(booking_id), now)

    def finalize(
        self,
        state: ConfirmationState,
        confirmation_key: str,
        request_hash: str,
        event_ref: str,
        now: datetime,
        *,
        recovered: bool = False,
    ) -> ConfirmedBooking:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT status, calendar_event_ref FROM bookings WHERE booking_id = ?",
                (str(state.booking_id),),
            ).fetchone()
            if current is not None and current["status"] == "confirmed":
                result = ConfirmedBooking(
                    request_id=state.request_id,
                    booking_id=state.booking_id,
                    service_id=state.service_id,
                    slot_start=state.slot_start,
                    slot_end=state.slot_end,
                    buffer_minutes=state.buffer_minutes,
                    timezone="Europe/Warsaw",
                    status="confirmed",
                    calendar_event_ref=current["calendar_event_ref"],
                    idempotent_replay=True,
                )
                connection.execute(
                    "INSERT INTO idempotency_keys(key, operation, request_hash, response_json, created_at) "
                    "VALUES (?, 'confirm_booking', ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET response_json = excluded.response_json",
                    (confirmation_key, request_hash, result.model_dump_json(), now.isoformat()),
                )
                connection.commit()
                return result
            connection.execute(
                "UPDATE bookings SET status = 'confirmed', calendar_event_ref = ? WHERE booking_id = ?",
                (event_ref, str(state.booking_id)),
            )
            connection.execute(
                "UPDATE booking_requests SET status = 'confirmed', customer_confirmed = 1 WHERE request_id = ?",
                (str(state.request_id),),
            )
            result = ConfirmedBooking(
                request_id=state.request_id,
                booking_id=state.booking_id,
                service_id=state.service_id,
                slot_start=state.slot_start,
                slot_end=state.slot_end,
                buffer_minutes=state.buffer_minutes,
                timezone="Europe/Warsaw",
                status="confirmed",
                calendar_event_ref=event_ref,
                idempotent_replay=recovered,
            )
            self._audit(
                connection,
                "booking.confirmed_recovered" if recovered else "booking.confirmed",
                "booking",
                str(state.booking_id),
                now,
            )
            connection.execute(
                "INSERT INTO idempotency_keys(key, operation, request_hash, response_json, created_at) "
                "VALUES (?, 'confirm_booking', ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET response_json = excluded.response_json",
                (confirmation_key, request_hash, result.model_dump_json(), now.isoformat()),
            )
            connection.commit()
            return result

    @staticmethod
    def _confirmed_from_rows(
        request_row: sqlite3.Row,
        booking_row: sqlite3.Row,
        *,
        replay: bool,
    ) -> ConfirmedBooking:
        service = next(item for item in DEMO_SERVICES if item.service_id == request_row["service_id"])
        return ConfirmedBooking(
            request_id=UUID(request_row["request_id"]),
            booking_id=UUID(booking_row["booking_id"]),
            service_id=request_row["service_id"],
            slot_start=datetime.fromisoformat(request_row["requested_start"]).astimezone(WARSAW),
            slot_end=datetime.fromisoformat(request_row["requested_end"]).astimezone(WARSAW),
            buffer_minutes=service.buffer_minutes,
            timezone="Europe/Warsaw",
            status="confirmed",
            calendar_event_ref=booking_row["calendar_event_ref"],
            idempotent_replay=replay,
        )
