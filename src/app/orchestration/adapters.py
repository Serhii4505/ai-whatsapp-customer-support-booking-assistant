"""Network-free mock adapters for outbound, manager and Google Sheets actions."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.orchestration.errors import (
    ConfirmedBookingNotFoundError,
    MockDeliveryUncertainError,
    MockIntegrationUnavailableError,
)
from app.orchestration.models import BookingSheetRow, BookingSheetSyncResult


WARSAW = ZoneInfo("Europe/Warsaw")


class MockOutboundMessenger:
    def __init__(
        self,
        *,
        unavailable: bool = False,
        fail_after_send_once: bool = False,
    ) -> None:
        self.unavailable = unavailable
        self.fail_after_send_once = fail_after_send_once
        self._sent: dict[str, str] = {}
        self._lock = Lock()

    def send(self, key: str, text: str) -> bool:
        if self.unavailable:
            raise MockIntegrationUnavailableError("mock outbound messenger is unavailable")
        with self._lock:
            replay = key in self._sent
            self._sent.setdefault(key, text)
            if self.fail_after_send_once and not replay:
                self.fail_after_send_once = False
                raise MockDeliveryUncertainError("mock outbound response was lost after delivery")
            return not replay

    def was_sent(self, key: str) -> bool:
        with self._lock:
            return key in self._sent

    @property
    def sent_count(self) -> int:
        with self._lock:
            return len(self._sent)


class MockManagerNotifier:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self._notifications: set[str] = set()
        self._lock = Lock()

    def notify(self, handoff_id: UUID) -> bool:
        if self.unavailable:
            raise MockIntegrationUnavailableError("mock manager notifier is unavailable")
        with self._lock:
            key = str(handoff_id)
            replay = key in self._notifications
            self._notifications.add(key)
            return not replay

    @property
    def notification_count(self) -> int:
        with self._lock:
            return len(self._notifications)


class MockGoogleSheetsAdapter:
    """SQLite-backed mock sheet with one authoritative row per booking."""

    def __init__(self, database_path: Path, *, unavailable: bool = False) -> None:
        self.database_path = database_path
        self.unavailable = unavailable

    def sync_confirmed_booking(
        self,
        booking_id: UUID,
        idempotency_key: str,
        now: datetime,
    ) -> BookingSheetSyncResult:
        if self.unavailable:
            raise MockIntegrationUnavailableError("mock Google Sheets is unavailable")
        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            booking = connection.execute(
                "SELECT b.booking_id, b.request_id, b.status, b.calendar_event_ref, "
                "r.service_id, r.requested_start, r.requested_end "
                "FROM bookings b JOIN booking_requests r ON r.request_id = b.request_id "
                "WHERE b.booking_id = ? AND b.status = 'confirmed' AND r.status = 'confirmed'",
                (str(booking_id),),
            ).fetchone()
            if booking is None:
                connection.rollback()
                raise ConfirmedBookingNotFoundError("confirmed booking does not exist")
            existing_key = connection.execute(
                "SELECT operation, request_hash, response_json FROM idempotency_keys WHERE key = ?",
                (idempotency_key,),
            ).fetchone()
            request_hash = str(booking_id)
            if existing_key is not None:
                if existing_key["operation"] != "sync_booking_sheet" or existing_key["request_hash"] != request_hash:
                    connection.rollback()
                    from app.orchestration.errors import WorkflowIdempotencyConflictError

                    raise WorkflowIdempotencyConflictError("sheet idempotency key was reused")
                connection.commit()
                return BookingSheetSyncResult.model_validate_json(existing_key["response_json"]).model_copy(
                    update={"idempotent_replay": True}
                )
            row = BookingSheetRow(
                booking_id=UUID(booking["booking_id"]),
                request_id=UUID(booking["request_id"]),
                service_id=booking["service_id"],
                slot_start=datetime.fromisoformat(booking["requested_start"]).astimezone(WARSAW),
                slot_end=datetime.fromisoformat(booking["requested_end"]).astimezone(WARSAW),
                status="confirmed",
                calendar_event_ref=booking["calendar_event_ref"],
            )
            cursor = connection.execute(
                "INSERT OR IGNORE INTO mock_sheet_bookings "
                "(booking_id, request_id, service_id, slot_start, slot_end, status, calendar_event_ref, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?)",
                (
                    str(row.booking_id), str(row.request_id), row.service_id,
                    row.slot_start.isoformat(), row.slot_end.isoformat(), row.calendar_event_ref,
                    now.isoformat(),
                ),
            )
            result = BookingSheetSyncResult(row=row, idempotent_replay=cursor.rowcount == 0)
            connection.execute(
                "INSERT INTO idempotency_keys(key, operation, request_hash, response_json, created_at) "
                "VALUES (?, 'sync_booking_sheet', ?, ?, ?)",
                (idempotency_key, request_hash, result.model_dump_json(), now.isoformat()),
            )
            if cursor.rowcount:
                connection.execute(
                    "INSERT INTO audit_events VALUES (?, 'booking.sheet_synced', 'system', 'booking', ?, '{}', ?)",
                    (str(uuid4()), str(booking_id), now.isoformat()),
                )
            connection.commit()
            return result
