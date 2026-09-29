"""Read-only availability endpoint backed by the mock calendar adapter."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.calendar.adapter import CalendarAvailabilityAdapter, MockGoogleCalendarAdapter
from app.calendar.definition import load_calendar_definition
from app.calendar.engine import AvailabilityEngine
from app.calendar.errors import (
    AvailabilityError,
    CalendarUnavailableError,
    InvalidCalendarResponseError,
)
from app.calendar.models import AvailabilityResponse, CalendarDefinition
from app.config import Settings


def build_calendar_router(
    settings: Settings,
    *,
    definition: CalendarDefinition | None = None,
    adapter: CalendarAvailabilityAdapter | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["availability"])
    resolved_definition = definition or load_calendar_definition(settings.calendar_config_path)
    resolved_adapter = adapter or MockGoogleCalendarAdapter.from_definition(resolved_definition)
    engine = AvailabilityEngine(resolved_definition, resolved_adapter)

    @router.get("/availability", response_model=AvailabilityResponse)
    def availability(
        service_id: str = Query(min_length=3, max_length=32),
        target_date: date = Query(alias="date"),
    ) -> AvailabilityResponse:
        try:
            return engine.available_slots(service_id, target_date)
        except (CalendarUnavailableError, InvalidCalendarResponseError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        except AvailabilityError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return router
