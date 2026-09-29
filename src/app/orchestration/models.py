"""Strict n8n orchestration and mock Sheets schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrchestrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrchestrationAction(StrEnum):
    SEND_GROUNDED_REPLY = "send_grounded_reply"
    CONTINUE_BOOKING_IN_PYTHON = "continue_booking_in_python"
    MANAGER_HANDOFF = "manager_handoff"


class WorkflowMessageCommand(OrchestrationModel):
    workflow_run_id: str = Field(min_length=16, max_length=128)
    provider_message_id: str = Field(min_length=1, max_length=200)
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=4096)


class WorkflowResult(OrchestrationModel):
    workflow_run_id: str
    provider_message_id: str
    action: OrchestrationAction
    intent: str
    response_text: str | None = Field(default=None, max_length=4096)
    source_ids: tuple[str, ...] = ()
    handoff_id: UUID | None = None
    manager_notified: bool = False
    outbound_sent: bool = False
    idempotent_replay: bool = False
    python_authoritative: bool = True


class BookingSheetSyncCommand(OrchestrationModel):
    idempotency_key: str = Field(min_length=16, max_length=128)


class BookingSheetRow(OrchestrationModel):
    booking_id: UUID
    request_id: UUID
    service_id: str
    slot_start: datetime
    slot_end: datetime
    status: str
    calendar_event_ref: str


class BookingSheetSyncResult(OrchestrationModel):
    synced: bool = True
    row: BookingSheetRow
    idempotent_replay: bool = False
    adapter: str = "mock_google_sheets"


class BookingFulfillmentCommand(OrchestrationModel):
    idempotency_key: str = Field(min_length=16, max_length=128)


class BookingFulfillmentResult(OrchestrationModel):
    booking_id: UUID
    sheet_synced: bool = True
    client_notified: bool = True
    delivery_key: str
    idempotent_replay: bool = False
    recovered_after_partial_failure: bool = False
    integrations: tuple[str, ...] = ("mock_google_sheets", "mock_outbound_messenger")
