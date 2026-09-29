"""Stable availability and calendar adapter errors."""


class AvailabilityError(ValueError):
    code = "availability_error"


class InvalidServiceError(AvailabilityError):
    code = "invalid_service"


class InvalidDateError(AvailabilityError):
    code = "invalid_date"


class AmbiguousLocalTimeError(AvailabilityError):
    code = "ambiguous_local_time"


class NonexistentLocalTimeError(AvailabilityError):
    code = "nonexistent_local_time"


class CalendarUnavailableError(AvailabilityError):
    code = "calendar_unavailable"


class InvalidCalendarResponseError(AvailabilityError):
    code = "invalid_calendar_response"

