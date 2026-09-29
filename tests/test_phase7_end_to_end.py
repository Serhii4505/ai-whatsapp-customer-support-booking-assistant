import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.ai.knowledge import ApprovedKnowledgeBase
from app.ai.provider import MockGeminiProvider
from app.ai.service import ControlledAIService
from app.booking.adapter import MockBookingCalendarAdapter
from app.booking.errors import EventCreationUncertainError
from app.booking.models import ConfirmBookingCommand, PrepareBookingCommand
from app.booking.repository import BookingRepository
from app.booking.service import BookingService
from app.calendar.definition import load_calendar_definition
from app.calendar.engine import AvailabilityEngine
from app.config import Settings
from app.main import create_app
from app.orchestration.adapters import (
    MockGoogleSheetsAdapter,
    MockManagerNotifier,
    MockOutboundMessenger,
)
from app.orchestration.errors import MockIntegrationUnavailableError
from app.orchestration.models import BookingFulfillmentCommand, WorkflowMessageCommand
from app.orchestration.service import OrchestrationService
from app.whatsapp.security import compute_signature


ROOT = Path(__file__).resolve().parents[1]
WARSAW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=WARSAW)
SECRET = "synthetic-phase-7-app-secret"


def signed_payload(provider_id: str, message: str) -> tuple[bytes, dict[str, str]]:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "synthetic-business-account",
            "changes": [{
                "field": "messages",
                "value": {"messages": [{
                    "id": provider_id,
                    "from": "48000000007",
                    "timestamp": "1790683200",
                    "type": "text",
                    "text": {"body": message},
                }]},
            }],
        }],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    return body, {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": compute_signature(body, SECRET),
    }


def build_pipeline(tmp_path: Path, *, outbound=None, sheets=None, provider=None):
    database_path = tmp_path / "assistant.sqlite3"
    settings = Settings(database_path=database_path, whatsapp_app_secret=SECRET)
    client = TestClient(create_app(settings))
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    calendar = MockBookingCalendarAdapter(definition.busy_intervals)
    availability = AvailabilityEngine(definition, calendar)
    booking = BookingService(BookingRepository(database_path), availability, calendar)
    knowledge = ApprovedKnowledgeBase.load(ROOT / "demo" / "knowledge_base.json")
    ai = ControlledAIService(provider or MockGeminiProvider(knowledge), knowledge, 0.75)
    outbound = outbound or MockOutboundMessenger()
    sheets = sheets or MockGoogleSheetsAdapter(database_path)
    orchestration = OrchestrationService(
        database_path, ai, outbound, MockManagerNotifier(), sheets
    )
    return client, database_path, availability, booking, calendar, orchestration, outbound, sheets


@pytest.mark.parametrize(
    ("service_id", "message"),
    [
        ("INTRO_CALL", "Book an introductory consultation"),
        ("STANDARD_VISIT", "Book a standard service appointment"),
        ("EXTENDED_SESSION", "Book an extended service session"),
    ],
)
def test_complete_signed_webhook_to_fulfillment_for_every_service(
    tmp_path: Path, service_id: str, message: str
) -> None:
    client, database_path, availability, booking, calendar, orchestration, outbound, _ = build_pipeline(
        tmp_path
    )
    provider_id = f"wamid.synthetic.phase7.{service_id.lower()}"
    body, headers = signed_payload(provider_id, message)
    with client:
        first_webhook = client.post("/webhooks/whatsapp", content=body, headers=headers)
        replay_webhook = client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert first_webhook.json()["processed"] == 1
    assert replay_webhook.json()["duplicates"] == 1

    with sqlite3.connect(database_path) as connection:
        conversation_id = connection.execute(
            "SELECT conversation_id FROM messages WHERE provider_message_id=?", (provider_id,)
        ).fetchone()[0]

    workflow = WorkflowMessageCommand(
        workflow_run_id=f"phase7-run-{service_id.lower()}-0001",
        provider_message_id=provider_id,
        conversation_id=conversation_id,
        message=message,
    )
    routed = orchestration.process_message(workflow)
    routed_replay = orchestration.process_message(workflow)
    assert routed.action == "continue_booking_in_python"
    assert routed_replay.idempotent_replay is True

    slots = availability.available_slots(service_id, datetime(2026, 9, 30).date(), now=NOW)
    chosen = slots.slots[0]
    prepared = booking.prepare(
        PrepareBookingCommand(
            conversation_id=conversation_id,
            service_id=service_id,
            slot_start=chosen.start,
            idempotency_key=f"prepare-phase7-{service_id.lower()}-0001",
        ),
        now=NOW,
    )
    assert calendar.events == ()
    confirmed = booking.confirm(
        prepared.request_id,
        ConfirmBookingCommand(
            confirmation="confirm",
            idempotency_key=f"confirm-phase7-{service_id.lower()}-0001",
        ),
        now=NOW,
    )
    fulfilled = orchestration.fulfill_booking(
        confirmed.booking_id,
        BookingFulfillmentCommand(
            idempotency_key=f"fulfill-phase7-{service_id.lower()}-0001"
        ),
    )
    replay = orchestration.fulfill_booking(
        confirmed.booking_id,
        BookingFulfillmentCommand(
            idempotency_key=f"fulfill-phase7-{service_id.lower()}-0001"
        ),
    )
    assert fulfilled.sheet_synced and fulfilled.client_notified
    assert replay.idempotent_replay is True
    assert len(calendar.events) == 1
    assert outbound.sent_count == 1
    with sqlite3.connect(database_path) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "messages", "bookings", "mock_sheet_bookings", "booking_fulfillments",
            )
        )
        states = connection.execute(
            "SELECT b.status, r.status, f.sheet_status, f.notification_status "
            "FROM bookings b JOIN booking_requests r ON r.request_id=b.request_id "
            "JOIN booking_fulfillments f ON f.booking_id=b.booking_id"
        ).fetchone()
    assert counts == (1, 1, 1, 1)
    assert states == ("confirmed", "confirmed", "synced", "mock_sent")


class FailingAIProvider:
    def analyze(self, _: str):
        raise RuntimeError("synthetic Gemini outage")


def test_gemini_failure_fails_closed_to_manager_handoff(tmp_path: Path) -> None:
    client, database_path, _, _, _, orchestration, _, _ = build_pipeline(
        tmp_path, provider=FailingAIProvider()
    )
    provider_id = "wamid.synthetic.phase7.gemini-failure"
    message = "Book an introductory consultation"
    body, headers = signed_payload(provider_id, message)
    with client:
        assert client.post("/webhooks/whatsapp", content=body, headers=headers).status_code == 200
    with sqlite3.connect(database_path) as connection:
        conversation_id = connection.execute("SELECT conversation_id FROM messages").fetchone()[0]
    result = orchestration.process_message(
        WorkflowMessageCommand(
            workflow_run_id="phase7-gemini-failure-0001",
            provider_message_id=provider_id,
            conversation_id=conversation_id,
            message=message,
        )
    )
    assert result.action == "manager_handoff"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM manager_handoffs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0


def create_confirmed_booking(tmp_path: Path, *, outbound=None, sheets=None):
    client, database_path, availability, booking, built_calendar, orchestration, outbound, sheets = build_pipeline(
        tmp_path, outbound=outbound, sheets=sheets
    )
    with client:
        body, headers = signed_payload("wamid.synthetic.phase7.fulfillment", "Book an introductory consultation")
        client.post("/webhooks/whatsapp", content=body, headers=headers)
    with sqlite3.connect(database_path) as connection:
        conversation_id = connection.execute("SELECT conversation_id FROM messages").fetchone()[0]
    slot = availability.available_slots("INTRO_CALL", datetime(2026, 9, 30).date(), now=NOW).slots[0]
    prepared = booking.prepare(
        PrepareBookingCommand(
            conversation_id=conversation_id,
            service_id="INTRO_CALL",
            slot_start=slot.start,
            idempotency_key="prepare-phase7-partial-0001",
        ), now=NOW,
    )
    confirmed = booking.confirm(
        prepared.request_id,
        ConfirmBookingCommand(confirmation="confirm", idempotency_key="confirm-phase7-partial-0001"),
        now=NOW,
    )
    return database_path, confirmed, orchestration, outbound, sheets, built_calendar, booking


def test_sheets_failure_is_recorded_and_retry_has_no_duplicates(tmp_path: Path) -> None:
    database_path = tmp_path / "assistant.sqlite3"
    sheets = MockGoogleSheetsAdapter(database_path, unavailable=True)
    database_path, confirmed, orchestration, outbound, sheets, calendar, _ = create_confirmed_booking(
        tmp_path, sheets=sheets
    )
    command = BookingFulfillmentCommand(idempotency_key="fulfill-phase7-sheet-retry-0001")
    with pytest.raises(MockIntegrationUnavailableError):
        orchestration.fulfill_booking(confirmed.booking_id, command)
    sheets.unavailable = False
    recovered = orchestration.fulfill_booking(confirmed.booking_id, command)
    replay = orchestration.fulfill_booking(confirmed.booking_id, command)
    assert recovered.sheet_synced and recovered.client_notified
    assert replay.idempotent_replay
    assert len(calendar.events) == outbound.sent_count == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mock_sheet_bookings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='booking.fulfillment_failed'"
        ).fetchone()[0] == 1


def test_lost_outbound_response_is_recovered_without_duplicate(tmp_path: Path) -> None:
    outbound = MockOutboundMessenger(fail_after_send_once=True)
    database_path, confirmed, orchestration, outbound, _, calendar, _ = create_confirmed_booking(
        tmp_path, outbound=outbound
    )
    result = orchestration.fulfill_booking(
        confirmed.booking_id,
        BookingFulfillmentCommand(idempotency_key="fulfill-phase7-lost-response-0001"),
    )
    assert result.recovered_after_partial_failure is True
    assert outbound.sent_count == len(calendar.events) == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mock_sheet_bookings").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM outbound_messages").fetchone()[0] == "mock_sent"


def test_outbound_outage_after_sheet_sync_recovers_without_duplicate(tmp_path: Path) -> None:
    outbound = MockOutboundMessenger(unavailable=True)
    database_path, confirmed, orchestration, outbound, _, calendar, _ = create_confirmed_booking(
        tmp_path, outbound=outbound
    )
    command = BookingFulfillmentCommand(idempotency_key="fulfill-phase7-outbound-retry-0001")
    with pytest.raises(MockIntegrationUnavailableError):
        orchestration.fulfill_booking(confirmed.booking_id, command)
    outbound.unavailable = False
    recovered = orchestration.fulfill_booking(confirmed.booking_id, command)
    replay = orchestration.fulfill_booking(confirmed.booking_id, command)
    assert recovered.sheet_synced and recovered.client_notified
    assert replay.idempotent_replay is True
    assert len(calendar.events) == outbound.sent_count == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mock_sheet_bookings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 1
        assert connection.execute(
            "SELECT sheet_status, notification_status FROM booking_fulfillments"
        ).fetchone() == ("synced", "mock_sent")


def test_calendar_lost_response_recovers_then_fulfills_once(tmp_path: Path) -> None:
    definition = load_calendar_definition(ROOT / "demo" / "calendar.json")
    calendar = MockBookingCalendarAdapter(definition.busy_intervals, fail_after_create_once=True)
    # Build through the same pipeline while preserving the failure-injected calendar.
    database_path = tmp_path / "assistant.sqlite3"
    client, database_path, availability, _, _, orchestration, outbound, _ = build_pipeline(tmp_path)
    booking = BookingService(BookingRepository(database_path), AvailabilityEngine(definition, calendar), calendar)
    with client:
        body, headers = signed_payload("wamid.synthetic.phase7.calendar-loss", "Book an introductory consultation")
        client.post("/webhooks/whatsapp", content=body, headers=headers)
    with sqlite3.connect(database_path) as connection:
        conversation_id = connection.execute("SELECT conversation_id FROM messages").fetchone()[0]
    slot = availability.available_slots("INTRO_CALL", datetime(2026, 9, 30).date(), now=NOW).slots[0]
    prepared = booking.prepare(
        PrepareBookingCommand(
            conversation_id=conversation_id, service_id="INTRO_CALL", slot_start=slot.start,
            idempotency_key="prepare-phase7-calendar-loss-0001",
        ), now=NOW,
    )
    confirm_command = ConfirmBookingCommand(
        confirmation="confirm", idempotency_key="confirm-phase7-calendar-loss-0001"
    )
    with pytest.raises(EventCreationUncertainError):
        booking.confirm(prepared.request_id, confirm_command, now=NOW)
    confirmed = booking.confirm(prepared.request_id, confirm_command, now=NOW)
    orchestration.fulfill_booking(
        confirmed.booking_id,
        BookingFulfillmentCommand(idempotency_key="fulfill-phase7-calendar-loss-0001"),
    )
    assert len(calendar.events) == outbound.sent_count == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM mock_sheet_bookings").fetchone()[0] == 1
