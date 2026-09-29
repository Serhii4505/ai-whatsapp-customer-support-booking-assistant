"""Python-authoritative orchestration used by the sanitized n8n workflow."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.ai.models import ResponseRoute
from app.ai.service import ControlledAIService
from app.orchestration.adapters import (
    MockGoogleSheetsAdapter,
    MockManagerNotifier,
    MockOutboundMessenger,
)
from app.orchestration.errors import (
    MockDeliveryUncertainError,
    MockIntegrationUnavailableError,
    SourceMessageNotFoundError,
    WorkflowIdempotencyConflictError,
)
from app.orchestration.models import (
    BookingSheetSyncCommand,
    BookingSheetSyncResult,
    BookingFulfillmentCommand,
    BookingFulfillmentResult,
    OrchestrationAction,
    WorkflowMessageCommand,
    WorkflowResult,
)


class OrchestrationService:
    def __init__(
        self,
        database_path: Path,
        ai: ControlledAIService,
        outbound: MockOutboundMessenger,
        manager: MockManagerNotifier,
        sheets: MockGoogleSheetsAdapter,
    ) -> None:
        self.database_path = database_path
        self.ai = ai
        self.outbound = outbound
        self.manager = manager
        self.sheets = sheets

    @staticmethod
    def _hash(command: WorkflowMessageCommand) -> str:
        payload = command.model_dump(mode="json", exclude={"workflow_run_id"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def process_message(self, command: WorkflowMessageCommand) -> WorkflowResult:
        now = datetime.now(timezone.utc)
        request_hash = self._hash(command)
        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM workflow_runs WHERE run_id = ? OR source_message_id = ?",
                (command.workflow_run_id, command.provider_message_id),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    connection.rollback()
                    raise WorkflowIdempotencyConflictError(
                        "workflow run or source message was reused with different content"
                    )
                connection.commit()
                return WorkflowResult.model_validate_json(existing["response_json"]).model_copy(
                    update={"idempotent_replay": True}
                )

            source = connection.execute(
                "SELECT conversation_id, status, text FROM messages WHERE provider_message_id = ?",
                (command.provider_message_id,),
            ).fetchone()
            if (
                source is None
                or source["conversation_id"] != str(command.conversation_id)
                or source["status"] != "received"
                or source["text"] != command.message
            ):
                connection.rollback()
                raise SourceMessageNotFoundError("validated source message does not exist")

            decision = self.ai.process(command.message)
            result: WorkflowResult
            workflow_status = "completed"

            if decision.route == ResponseRoute.GROUNDED_ANSWER:
                try:
                    sent_now = self.outbound.send(
                        f"reply:{command.provider_message_id}", decision.response_text or ""
                    )
                    connection.execute(
                        "INSERT INTO outbound_messages "
                        "(delivery_key, source_message_id, text, status, created_at) VALUES (?, ?, ?, 'mock_sent', ?)",
                        (
                            f"reply:{command.provider_message_id}", command.provider_message_id,
                            decision.response_text, now.isoformat(),
                        ),
                    )
                    result = WorkflowResult(
                        workflow_run_id=command.workflow_run_id,
                        provider_message_id=command.provider_message_id,
                        action=OrchestrationAction.SEND_GROUNDED_REPLY,
                        intent=decision.intent.value,
                        response_text=decision.response_text,
                        source_ids=decision.source_ids,
                        outbound_sent=sent_now,
                    )
                except MockIntegrationUnavailableError:
                    result = self._create_handoff(
                        connection, command, decision.intent.value, "outbound_delivery_failed", now
                    )
                    workflow_status = "attention_required"
            elif decision.route == ResponseRoute.MANAGER_HANDOFF:
                result = self._create_handoff(
                    connection,
                    command,
                    decision.intent.value,
                    decision.handoff_reason or "manager_review_required",
                    now,
                )
                workflow_status = "attention_required"
            else:
                result = WorkflowResult(
                    workflow_run_id=command.workflow_run_id,
                    provider_message_id=command.provider_message_id,
                    action=OrchestrationAction.CONTINUE_BOOKING_IN_PYTHON,
                    intent=decision.intent.value,
                )

            connection.execute(
                "INSERT INTO workflow_runs "
                "(run_id, source_message_id, request_hash, action, response_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    command.workflow_run_id, command.provider_message_id, request_hash,
                    result.action.value, result.model_dump_json(), workflow_status, now.isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES (?, 'workflow.processed', 'system', 'message', ?, ?, ?)",
                (
                    str(uuid4()), command.provider_message_id,
                    json.dumps({"action": result.action.value, "status": workflow_status}, sort_keys=True),
                    now.isoformat(),
                ),
            )
            connection.commit()
            return result

    def _create_handoff(
        self,
        connection: sqlite3.Connection,
        command: WorkflowMessageCommand,
        intent: str,
        reason: str,
        now: datetime,
    ) -> WorkflowResult:
        handoff_id = uuid5(NAMESPACE_URL, f"handoff:{command.provider_message_id}")
        summary = f"Manager review required for intent '{intent}'. Reason: {reason}."
        connection.execute(
            "INSERT INTO manager_handoffs "
            "(handoff_id, source_message_id, reason, summary, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (str(handoff_id), command.provider_message_id, reason, summary, now.isoformat()),
        )
        notified = False
        notification_status = "failed"
        try:
            notified = self.manager.notify(handoff_id)
            notification_status = "mock_sent"
        except MockIntegrationUnavailableError:
            notification_status = "failed"
        connection.execute(
            "INSERT INTO manager_notifications "
            "(notification_id, handoff_id, status, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid4()), str(handoff_id), notification_status, now.isoformat()),
        )
        connection.execute(
            "INSERT INTO audit_events VALUES (?, 'manager.handoff_created', 'system', 'handoff', ?, ?, ?)",
            (
                str(uuid4()), str(handoff_id),
                json.dumps({"reason": reason, "notification_status": notification_status}, sort_keys=True),
                now.isoformat(),
            ),
        )
        return WorkflowResult(
            workflow_run_id=command.workflow_run_id,
            provider_message_id=command.provider_message_id,
            action=OrchestrationAction.MANAGER_HANDOFF,
            intent=intent,
            handoff_id=handoff_id,
            manager_notified=notified,
        )

    def sync_booking(
        self,
        booking_id: UUID,
        command: BookingSheetSyncCommand,
    ) -> BookingSheetSyncResult:
        return self.sheets.sync_confirmed_booking(
            booking_id,
            command.idempotency_key,
            datetime.now(timezone.utc),
        )

    def fulfill_booking(
        self,
        booking_id: UUID,
        command: BookingFulfillmentCommand,
    ) -> BookingFulfillmentResult:
        """Synchronize a confirmed booking and notify once, with replay recovery."""

        now = datetime.now(timezone.utc)
        delivery_key = f"booking-confirmed:{booking_id}"
        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            connection.row_factory = sqlite3.Row
            existing = connection.execute(
                "SELECT response_json FROM booking_fulfillments WHERE booking_id = ?",
                (str(booking_id),),
            ).fetchone()
            if existing is not None and existing["response_json"]:
                return BookingFulfillmentResult.model_validate_json(
                    existing["response_json"]
                ).model_copy(update={"idempotent_replay": True})

        sheet_key = hashlib.sha256(
            f"sheet:{command.idempotency_key}:{booking_id}".encode()
        ).hexdigest()
        try:
            sheet_result = self.sheets.sync_confirmed_booking(booking_id, sheet_key, now)
        except MockIntegrationUnavailableError as exc:
            self._record_fulfillment_failure(
                booking_id, delivery_key, "failed", "not_started", exc.code, now
            )
            raise

        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                connection.execute(
                    "INSERT INTO booking_fulfillments "
                    "(booking_id, sheet_status, notification_status, delivery_key, response_json, last_error, updated_at) "
                    "VALUES (?, 'synced', 'pending', ?, NULL, NULL, ?) "
                    "ON CONFLICT(booking_id) DO UPDATE SET sheet_status='synced', updated_at=excluded.updated_at",
                    (str(booking_id), delivery_key, now.isoformat()),
                )
                outbound = connection.execute(
                    "SELECT status FROM outbound_messages WHERE delivery_key = ?",
                    (delivery_key,),
                ).fetchone()
                already_notified = outbound is not None and outbound["status"] == "mock_sent"
                if outbound is None:
                    connection.execute(
                        "INSERT INTO outbound_messages "
                        "(delivery_key, source_message_id, text, status, created_at) "
                        "VALUES (?, ?, ?, 'pending', ?)",
                        (
                            delivery_key,
                            f"booking:{booking_id}",
                            self._confirmation_text(sheet_result),
                            now.isoformat(),
                        ),
                    )

        recovered = False
        if not already_notified:
            try:
                self.outbound.send(delivery_key, self._confirmation_text(sheet_result))
            except MockDeliveryUncertainError:
                if not self.outbound.was_sent(delivery_key):
                    self._record_fulfillment_failure(
                        booking_id, delivery_key, "synced", "failed", "mock_delivery_uncertain", now
                    )
                    raise
                recovered = True
            except MockIntegrationUnavailableError as exc:
                self._record_fulfillment_failure(
                    booking_id, delivery_key, "synced", "failed", exc.code, now
                )
                raise

        result = BookingFulfillmentResult(
            booking_id=booking_id,
            delivery_key=delivery_key,
            idempotent_replay=already_notified,
            recovered_after_partial_failure=recovered,
        )
        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            with connection:
                connection.execute(
                    "UPDATE outbound_messages SET status='mock_sent' WHERE delivery_key = ?",
                    (delivery_key,),
                )
                connection.execute(
                    "UPDATE booking_fulfillments SET sheet_status='synced', notification_status='mock_sent', "
                    "response_json=?, last_error=NULL, updated_at=? WHERE booking_id=?",
                    (result.model_dump_json(), now.isoformat(), str(booking_id)),
                )
                connection.execute(
                    "INSERT INTO audit_events VALUES (?, 'booking.fulfilled', 'system', 'booking', ?, ?, ?)",
                    (
                        str(uuid4()),
                        str(booking_id),
                        json.dumps({"recovered": recovered}, sort_keys=True),
                        now.isoformat(),
                    ),
                )
        return result

    @staticmethod
    def _confirmation_text(sheet_result: BookingSheetSyncResult) -> str:
        row = sheet_result.row
        return (
            f"Your demo booking for {row.service_id} is confirmed for "
            f"{row.slot_start.isoformat()}. Reference: {row.calendar_event_ref}."
        )

    def _record_fulfillment_failure(
        self,
        booking_id: UUID,
        delivery_key: str,
        sheet_status: str,
        notification_status: str,
        error_code: str,
        now: datetime,
    ) -> None:
        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO booking_fulfillments "
                    "(booking_id, sheet_status, notification_status, delivery_key, response_json, last_error, updated_at) "
                    "SELECT ?, ?, ?, ?, NULL, ?, ? WHERE EXISTS "
                    "(SELECT 1 FROM bookings WHERE booking_id = ?) "
                    "ON CONFLICT(booking_id) DO UPDATE SET sheet_status=excluded.sheet_status, "
                    "notification_status=excluded.notification_status, last_error=excluded.last_error, "
                    "updated_at=excluded.updated_at",
                    (
                        str(booking_id), sheet_status, notification_status, delivery_key,
                        error_code, now.isoformat(), str(booking_id),
                    ),
                )
                connection.execute(
                    "INSERT INTO audit_events VALUES (?, 'booking.fulfillment_failed', 'system', 'booking', ?, ?, ?)",
                    (
                        str(uuid4()), str(booking_id),
                        json.dumps({"code": error_code}, sort_keys=True), now.isoformat(),
                    ),
                )
