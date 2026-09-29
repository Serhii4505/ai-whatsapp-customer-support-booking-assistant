"""FastAPI routes for selection and explicit booking confirmation."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.booking.adapter import MockBookingCalendarAdapter
from app.booking.errors import BookingWorkflowError
from app.booking.models import (
    ConfirmBookingCommand,
    ConfirmedBooking,
    PrepareBookingCommand,
    PreparedBooking,
)
from app.booking.repository import BookingRepository
from app.booking.service import BookingService
from app.calendar.engine import AvailabilityEngine
from app.calendar.errors import AvailabilityError, CalendarUnavailableError, InvalidCalendarResponseError
from app.config import Settings


def build_booking_router(
    settings: Settings,
    calendar: MockBookingCalendarAdapter,
    availability: AvailabilityEngine,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])
    service = BookingService(BookingRepository(settings.database_path), availability, calendar)

    @router.post("/prepare", response_model=PreparedBooking)
    def prepare(command: PrepareBookingCommand) -> PreparedBooking:
        try:
            return service.prepare(command)
        except (CalendarUnavailableError, InvalidCalendarResponseError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        except (BookingWorkflowError, AvailabilityError) as exc:
            raise HTTPException(
                status_code=getattr(exc, "http_status", 422),
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post("/{request_id}/confirm", response_model=ConfirmedBooking)
    def confirm(request_id: UUID, command: ConfirmBookingCommand) -> ConfirmedBooking:
        try:
            return service.confirm(request_id, command)
        except (CalendarUnavailableError, InvalidCalendarResponseError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        except (BookingWorkflowError, AvailabilityError) as exc:
            raise HTTPException(
                status_code=getattr(exc, "http_status", 422),
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return router

