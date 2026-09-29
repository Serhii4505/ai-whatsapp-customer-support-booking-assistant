"""Protected-by-network-boundary endpoints intended for local n8n orchestration."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.ai.knowledge import ApprovedKnowledgeBase
from app.ai.provider import MockGeminiProvider
from app.ai.service import ControlledAIService
from app.config import Settings
from app.orchestration.adapters import (
    MockGoogleSheetsAdapter,
    MockManagerNotifier,
    MockOutboundMessenger,
)
from app.orchestration.errors import OrchestrationError
from app.orchestration.models import (
    BookingFulfillmentCommand,
    BookingFulfillmentResult,
    BookingSheetSyncCommand,
    BookingSheetSyncResult,
    WorkflowMessageCommand,
    WorkflowResult,
)
from app.orchestration.service import OrchestrationService


def build_orchestration_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/orchestration", tags=["orchestration"])
    knowledge = ApprovedKnowledgeBase.load(settings.knowledge_base_path)
    ai = ControlledAIService(
        MockGeminiProvider(knowledge), knowledge, settings.ai_min_confidence
    )
    service = OrchestrationService(
        settings.database_path,
        ai,
        MockOutboundMessenger(),
        MockManagerNotifier(),
        MockGoogleSheetsAdapter(settings.database_path),
    )

    @router.post("/process", response_model=WorkflowResult)
    def process(command: WorkflowMessageCommand) -> WorkflowResult:
        try:
            return service.process_message(command)
        except OrchestrationError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post("/bookings/{booking_id}/sync", response_model=BookingSheetSyncResult)
    def sync_booking(
        booking_id: UUID,
        command: BookingSheetSyncCommand,
    ) -> BookingSheetSyncResult:
        try:
            return service.sync_booking(booking_id, command)
        except OrchestrationError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post("/bookings/{booking_id}/fulfill", response_model=BookingFulfillmentResult)
    def fulfill_booking(
        booking_id: UUID,
        command: BookingFulfillmentCommand,
    ) -> BookingFulfillmentResult:
        try:
            return service.fulfill_booking(booking_id, command)
        except OrchestrationError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return router
