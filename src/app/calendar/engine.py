"""Deterministic availability calculation owned entirely by Python."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.calendar.adapter import CalendarAvailabilityAdapter
from app.calendar.errors import (
    CalendarUnavailableError,
    InvalidCalendarResponseError,
    InvalidDateError,
    InvalidServiceError,
)
from app.calendar.models import AvailabilityResponse, AvailableSlot, BusyInterval, CalendarDefinition
from app.calendar.timezone import strict_local_datetime
from app.domain import DEMO_SERVICES, DemoService


class AvailabilityEngine:
    def __init__(self, definition: CalendarDefinition, adapter: CalendarAvailabilityAdapter) -> None:
        self.definition = definition
        self.adapter = adapter
        self.zone = ZoneInfo(definition.timezone)
        self.services = {service.service_id: service for service in DEMO_SERVICES}

    def available_slots(
        self,
        service_id: str,
        target_date: date,
        *,
        now: datetime | None = None,
    ) -> AvailabilityResponse:
        service = self._resolve_service(service_id)
        local_now = self._local_now(now)
        self._validate_date(target_date, local_now.date())

        if target_date.weekday() not in self.definition.working_days:
            return self._response(service, target_date, ())

        opens = strict_local_datetime(target_date, self.definition.opens_at, self.zone)
        closes = strict_local_datetime(target_date, self.definition.closes_at, self.zone)
        if target_date == local_now.date() and local_now >= closes:
            return self._response(service, target_date, ())

        try:
            raw_busy = self.adapter.get_busy(opens, closes)
        except CalendarUnavailableError:
            raise
        except Exception as exc:
            raise CalendarUnavailableError("calendar availability query failed") from exc
        busy = self._validate_busy_response(raw_busy)

        candidate = opens
        if target_date == local_now.date() and local_now > opens:
            elapsed_minutes = (local_now - opens).total_seconds() / 60
            steps = math.ceil(elapsed_minutes / self.definition.slot_interval_minutes)
            candidate = opens + timedelta(minutes=steps * self.definition.slot_interval_minutes)

        slots: list[AvailableSlot] = []
        service_duration = timedelta(minutes=service.duration_minutes)
        blocked_duration = timedelta(minutes=service.duration_minutes + service.buffer_minutes)
        step = timedelta(minutes=self.definition.slot_interval_minutes)

        while candidate + blocked_duration <= closes:
            blocked_end = candidate + blocked_duration
            if not any(candidate < interval.end and blocked_end > interval.start for interval in busy):
                slots.append(
                    AvailableSlot(
                        service_id=service.service_id,
                        start=candidate,
                        end=candidate + service_duration,
                    )
                )
            candidate += step

        return self._response(service, target_date, tuple(slots))

    def _resolve_service(self, service_id: str) -> DemoService:
        if not isinstance(service_id, str) or service_id not in self.services:
            raise InvalidServiceError("service_id is not in the approved catalogue")
        return self.services[service_id]

    def _local_now(self, now: datetime | None) -> datetime:
        resolved = now or datetime.now(self.zone)
        if resolved.tzinfo is None or resolved.utcoffset() is None:
            raise InvalidDateError("now must be timezone-aware")
        return resolved.astimezone(self.zone)

    def _validate_date(self, target_date: date, today: date) -> None:
        if target_date < today:
            raise InvalidDateError("availability cannot be requested for a past date")
        if target_date > today + timedelta(days=self.definition.max_days_ahead):
            raise InvalidDateError("availability date exceeds the configured planning horizon")

    @staticmethod
    def _validate_busy_response(raw: object) -> tuple[BusyInterval, ...]:
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise InvalidCalendarResponseError("calendar busy response must be a sequence")
        result: list[BusyInterval] = []
        for item in raw:
            if not isinstance(item, BusyInterval):
                raise InvalidCalendarResponseError("calendar returned an invalid busy interval")
            if (
                item.start.tzinfo is None
                or item.start.utcoffset() is None
                or item.end.tzinfo is None
                or item.end.utcoffset() is None
                or item.end <= item.start
                or item.end - item.start > timedelta(days=7)
            ):
                raise InvalidCalendarResponseError("calendar returned an invalid busy interval")
            result.append(item)
        return tuple(sorted(result, key=lambda item: (item.start, item.end)))

    def _response(
        self,
        service: DemoService,
        target_date: date,
        slots: tuple[AvailableSlot, ...],
    ) -> AvailabilityResponse:
        return AvailabilityResponse(
            calendar_id=self.definition.calendar_id,
            service_id=service.service_id,
            date=target_date,
            timezone=self.definition.timezone,
            service_duration_minutes=service.duration_minutes,
            buffer_minutes=service.buffer_minutes,
            slots=slots,
        )

