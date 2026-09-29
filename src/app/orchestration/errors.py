"""Stable orchestration errors."""


class OrchestrationError(RuntimeError):
    code = "orchestration_error"
    http_status = 422


class SourceMessageNotFoundError(OrchestrationError):
    code = "source_message_not_found"
    http_status = 404


class WorkflowIdempotencyConflictError(OrchestrationError):
    code = "workflow_idempotency_conflict"
    http_status = 409


class ConfirmedBookingNotFoundError(OrchestrationError):
    code = "confirmed_booking_not_found"
    http_status = 404


class MockIntegrationUnavailableError(OrchestrationError):
    code = "mock_integration_unavailable"
    http_status = 503


class MockDeliveryUncertainError(MockIntegrationUnavailableError):
    code = "mock_delivery_uncertain"
