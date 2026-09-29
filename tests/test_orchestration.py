import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai.knowledge import ApprovedKnowledgeBase
from app.ai.provider import MockGeminiProvider
from app.ai.service import ControlledAIService
from app.database import initialize_database
from app.orchestration.adapters import (
    MockGoogleSheetsAdapter,
    MockManagerNotifier,
    MockOutboundMessenger,
)
from app.orchestration.errors import (
    ConfirmedBookingNotFoundError,
    MockIntegrationUnavailableError,
    SourceMessageNotFoundError,
    WorkflowIdempotencyConflictError,
)
from app.orchestration.models import BookingSheetSyncCommand, WorkflowMessageCommand
from app.orchestration.service import OrchestrationService


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def build_service(
    tmp_path: Path,
    *,
    outbound_unavailable: bool = False,
    manager_unavailable: bool = False,
    sheets_unavailable: bool = False,
):
    database_path = tmp_path / "assistant.sqlite3"
    initialize_database(database_path)
    knowledge = ApprovedKnowledgeBase.load(ROOT / "demo" / "knowledge_base.json")
    ai = ControlledAIService(MockGeminiProvider(knowledge), knowledge, 0.75)
    outbound = MockOutboundMessenger(unavailable=outbound_unavailable)
    manager = MockManagerNotifier(unavailable=manager_unavailable)
    sheets = MockGoogleSheetsAdapter(database_path, unavailable=sheets_unavailable)
    service = OrchestrationService(database_path, ai, outbound, manager, sheets)
    return service, outbound, manager, database_path


def seed_message(database_path: Path, provider_id: str, text: str):
    contact_id, conversation_id, message_id = uuid4(), uuid4(), uuid4()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO contacts VALUES (?, 'Synthetic', ?, 'en', 1, ?)",
            (str(contact_id), f"synthetic-{contact_id}", NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO conversations VALUES (?, ?, 'active', 'en', 0, ?, ?)",
            (str(conversation_id), str(contact_id), NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, 'inbound', 'received', ?, ?)",
            (str(message_id), str(conversation_id), provider_id, text, NOW.isoformat()),
        )
    return conversation_id


def command(run_id: str, provider_id: str, conversation_id, message: str):
    return WorkflowMessageCommand(
        workflow_run_id=run_id,
        provider_message_id=provider_id,
        conversation_id=conversation_id,
        message=message,
    )


def test_grounded_reply_and_workflow_replay_do_not_duplicate_output(tmp_path: Path) -> None:
    service, outbound, _, database_path = build_service(tmp_path)
    text = "What are your opening hours?"
    conversation_id = seed_message(database_path, "wamid.synthetic.flow.001", text)
    cmd = command("workflow-run-00000001", "wamid.synthetic.flow.001", conversation_id, text)
    first = service.process_message(cmd)
    replay = service.process_message(cmd)
    assert first.action == "send_grounded_reply"
    assert first.outbound_sent is True
    assert replay.idempotent_replay is True
    assert outbound.sent_count == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 1


def test_unknown_request_creates_one_handoff_and_notification(tmp_path: Path) -> None:
    service, _, manager, database_path = build_service(tmp_path)
    text = "Tell me something surprising"
    conversation_id = seed_message(database_path, "wamid.synthetic.flow.002", text)
    cmd = command("workflow-run-00000002", "wamid.synthetic.flow.002", conversation_id, text)
    first = service.process_message(cmd)
    replay = service.process_message(cmd)
    assert first.action == "manager_handoff"
    assert first.manager_notified is True
    assert replay.idempotent_replay is True
    assert manager.notification_count == 1
    with sqlite3.connect(database_path) as connection:
        handoff = connection.execute("SELECT reason, summary FROM manager_handoffs").fetchone()
        assert connection.execute("SELECT COUNT(*) FROM manager_handoffs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM manager_notifications").fetchone()[0] == 1
    assert text not in handoff[1]


def test_manager_notification_failure_is_recorded_without_losing_handoff(tmp_path: Path) -> None:
    service, _, _, database_path = build_service(tmp_path, manager_unavailable=True)
    text = "I need a manager"
    conversation_id = seed_message(database_path, "wamid.synthetic.flow.003", text)
    result = service.process_message(
        command("workflow-run-00000003", "wamid.synthetic.flow.003", conversation_id, text)
    )
    assert result.action == "manager_handoff"
    assert result.manager_notified is False
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT status FROM manager_notifications").fetchone()[0] == "failed"
        assert connection.execute("SELECT status FROM workflow_runs").fetchone()[0] == "attention_required"


def test_outbound_failure_routes_to_manager(tmp_path: Path) -> None:
    service, _, manager, database_path = build_service(tmp_path, outbound_unavailable=True)
    text = "What are your opening hours?"
    conversation_id = seed_message(database_path, "wamid.synthetic.flow.004", text)
    result = service.process_message(
        command("workflow-run-00000004", "wamid.synthetic.flow.004", conversation_id, text)
    )
    assert result.action == "manager_handoff"
    assert manager.notification_count == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT reason FROM manager_handoffs").fetchone()[0] == "outbound_delivery_failed"


def test_booking_intent_only_routes_back_to_python(tmp_path: Path) -> None:
    service, outbound, manager, database_path = build_service(tmp_path)
    text = "Book an introductory consultation tomorrow at 14:30"
    conversation_id = seed_message(database_path, "wamid.synthetic.flow.005", text)
    result = service.process_message(
        command("workflow-run-00000005", "wamid.synthetic.flow.005", conversation_id, text)
    )
    assert result.action == "continue_booking_in_python"
    assert result.python_authoritative is True
    assert outbound.sent_count == 0
    assert manager.notification_count == 0


def test_unvalidated_source_and_conflicting_reuse_are_rejected(tmp_path: Path) -> None:
    service, _, _, database_path = build_service(tmp_path)
    with pytest.raises(SourceMessageNotFoundError):
        service.process_message(
            command("workflow-run-00000006", "missing", uuid4(), "Unknown")
        )
    text = "What services do you offer?"
    conversation_id = seed_message(database_path, "wamid.synthetic.flow.006", text)
    service.process_message(
        command("workflow-run-00000007", "wamid.synthetic.flow.006", conversation_id, text)
    )
    with pytest.raises(WorkflowIdempotencyConflictError):
        service.process_message(
            command("workflow-run-00000007", "wamid.synthetic.flow.006", conversation_id, "Changed text")
        )


def seed_confirmed_booking(database_path: Path):
    contact_id, conversation_id, request_id, booking_id = uuid4(), uuid4(), uuid4(), uuid4()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO contacts VALUES (?, 'Synthetic', ?, 'en', 1, ?)",
            (str(contact_id), f"synthetic-{contact_id}", NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO conversations VALUES (?, ?, 'active', 'en', 0, ?, ?)",
            (str(conversation_id), str(contact_id), NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO booking_requests VALUES (?, ?, 'INTRO_CALL', ?, ?, 'confirmed', 1, ?)",
            (
                str(request_id), str(conversation_id), "2026-09-30T09:00:00+02:00",
                "2026-09-30T09:30:00+02:00", "2026-09-29T12:15:00+02:00",
            ),
        )
        connection.execute(
            "INSERT INTO bookings VALUES (?, ?, ?, 'mock-event-synthetic', 'confirmed', ?)",
            (str(booking_id), str(request_id), f"booking-{booking_id}", NOW.isoformat()),
        )
    return booking_id


def test_mock_sheet_sync_is_idempotent_and_confirmed_only(tmp_path: Path) -> None:
    service, _, _, database_path = build_service(tmp_path)
    booking_id = seed_confirmed_booking(database_path)
    command_one = BookingSheetSyncCommand(idempotency_key="sheet-sync-key-000001")
    first = service.sync_booking(booking_id, command_one)
    replay = service.sync_booking(booking_id, command_one)
    another_key = service.sync_booking(
        booking_id, BookingSheetSyncCommand(idempotency_key="sheet-sync-key-000002")
    )
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert another_key.idempotent_replay is True
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mock_sheet_bookings").fetchone()[0] == 1

    with pytest.raises(ConfirmedBookingNotFoundError):
        service.sync_booking(
            uuid4(), BookingSheetSyncCommand(idempotency_key="sheet-sync-key-000003")
        )


def test_mock_sheet_unavailability_is_safe(tmp_path: Path) -> None:
    service, _, _, database_path = build_service(tmp_path, sheets_unavailable=True)
    booking_id = seed_confirmed_booking(database_path)
    with pytest.raises(MockIntegrationUnavailableError):
        service.sync_booking(
            booking_id, BookingSheetSyncCommand(idempotency_key="sheet-sync-key-000004")
        )


def test_n8n_export_is_inactive_and_sanitized() -> None:
    path = ROOT / "n8n" / "phase-6-whatsapp-booking-orchestration.workflow.json"
    raw = path.read_text(encoding="utf-8")
    workflow = json.loads(raw)
    assert workflow["active"] is False
    assert len(workflow["nodes"]) == 7
    assert "$env.FASTAPI_BASE_URL" in raw
    assert "/fulfill" in raw
    assert "/sync\"" not in raw
    forbidden_keys = {"credentials", "webhookId", "pinData", "versionId", "meta"}

    def collect_keys(value):
        if isinstance(value, dict):
            return set(value).union(*(collect_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(collect_keys(item) for item in value)) if value else set()
        return set()

    assert not forbidden_keys.intersection(collect_keys(workflow))
    assert "access_token" not in raw.lower()
    assert "client_secret" not in raw.lower()
    assert "@gmail.com" not in raw.lower()
