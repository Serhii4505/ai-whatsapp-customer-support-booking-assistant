"""FastAPI entry point for the mock-first booking assistant."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.config import Settings, get_settings
from app.ai.router import build_ai_router
from app.booking.adapter import MockBookingCalendarAdapter
from app.booking.router import build_booking_router
from app.calendar.definition import load_calendar_definition
from app.calendar.engine import AvailabilityEngine
from app.calendar.router import build_calendar_router
from app.database import DatabaseError, database_health, initialize_database
from app.domain import HealthResponse
from app.orchestration.router import build_orchestration_router
from app.whatsapp.router import build_whatsapp_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(resolved.database_path)
        yield

    application = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        description="Mock-first customer support and booking assistant using synthetic data only.",
        lifespan=lifespan,
    )
    application.state.settings = resolved
    calendar_definition = load_calendar_definition(resolved.calendar_config_path)
    booking_calendar = MockBookingCalendarAdapter(calendar_definition.busy_intervals)
    availability_engine = AvailabilityEngine(calendar_definition, booking_calendar)
    application.include_router(build_whatsapp_router(resolved))
    application.include_router(build_ai_router(resolved))
    application.include_router(
        build_calendar_router(
            resolved,
            definition=calendar_definition,
            adapter=booking_calendar,
        )
    )
    application.include_router(build_booking_router(resolved, booking_calendar, availability_engine))
    application.include_router(build_orchestration_router(resolved))

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        if not database_health(resolved.database_path):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "database_unavailable", "message": "Database health check failed"},
            )
        return HealthResponse(
            status="ok",
            service=resolved.app_name,
            version=resolved.app_version,
            environment=resolved.app_env,
            database="ok",
            company=resolved.demo_company,
            timezone=resolved.business_timezone,
            integrations={
                "whatsapp": resolved.whatsapp_mode,
                "calendar": resolved.calendar_mode,
                "crm": resolved.crm_mode,
                "gemini": resolved.gemini_mode,
            },
            data_policy="synthetic_only",
        )

    @application.exception_handler(DatabaseError)
    async def database_error_handler(_, exc: DatabaseError):  # type: ignore[no-untyped-def]
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": {"code": "database_initialization_failed", "message": str(exc)}},
        )

    return application


app = create_app()
