"""Stable booking workflow errors."""


class BookingWorkflowError(RuntimeError):
    code = "booking_error"
    http_status = 422


class ConversationNotFoundError(BookingWorkflowError):
    code = "conversation_not_found"
    http_status = 404


class BookingRequestNotFoundError(BookingWorkflowError):
    code = "booking_request_not_found"
    http_status = 404


class ExplicitConfirmationRequiredError(BookingWorkflowError):
    code = "explicit_confirmation_required"


class InvalidBookingStateError(BookingWorkflowError):
    code = "invalid_booking_state"
    http_status = 409


class SlotUnavailableError(BookingWorkflowError):
    code = "slot_unavailable"
    http_status = 409


class IdempotencyConflictError(BookingWorkflowError):
    code = "idempotency_conflict"
    http_status = 409


class EventCreationError(BookingWorkflowError):
    code = "event_creation_failed"
    http_status = 503


class EventCreationUncertainError(EventCreationError):
    code = "event_creation_uncertain"

