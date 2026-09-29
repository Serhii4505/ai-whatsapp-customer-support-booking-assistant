"""Strict schemas for AI classification and controlled responses."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CustomerIntent(StrEnum):
    FAQ = "faq"
    CHECK_AVAILABILITY = "check_availability"
    BOOKING_REQUEST = "booking_request"
    CONFIRM_BOOKING = "confirm_booking"
    HUMAN_HANDOFF = "human_handoff"
    UNKNOWN = "unknown"


class ResponseRoute(StrEnum):
    GROUNDED_ANSWER = "grounded_answer"
    PYTHON_BOOKING_FLOW = "python_booking_flow"
    MANAGER_HANDOFF = "manager_handoff"


class ExtractedCustomerData(AIModel):
    service_id: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,31}$")
    requested_date_text: str | None = Field(default=None, max_length=80)
    requested_time_text: str | None = Field(default=None, max_length=80)
    manager_requested: bool = False
    unrecognized_service: str | None = Field(default=None, max_length=100)


class StructuredAIResult(AIModel):
    intent: CustomerIntent
    confidence: float = Field(ge=0.0, le=1.0)
    extracted: ExtractedCustomerData = Field(default_factory=ExtractedCustomerData)
    requires_handoff: bool = False
    risk_flags: tuple[str, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def enforce_handoff_intent(self) -> "StructuredAIResult":
        if self.intent == CustomerIntent.HUMAN_HANDOFF and not self.requires_handoff:
            raise ValueError("human_handoff intent must require handoff")
        return self


class ControlledResponse(AIModel):
    intent: CustomerIntent
    route: ResponseRoute
    response_text: str | None = Field(default=None, max_length=4096)
    source_ids: tuple[str, ...] = ()
    extracted: ExtractedCustomerData = Field(default_factory=ExtractedCustomerData)
    handoff_reason: str | None = Field(default=None, max_length=200)
    side_effects: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_no_ai_side_effects(self) -> "ControlledResponse":
        if self.side_effects:
            raise ValueError("AI responses cannot contain side effects")
        if self.route == ResponseRoute.GROUNDED_ANSWER:
            if not self.response_text or not self.source_ids:
                raise ValueError("grounded answers require text and source IDs")
        if self.route == ResponseRoute.MANAGER_HANDOFF and not self.handoff_reason:
            raise ValueError("manager handoff requires a reason")
        return self


class CustomerMessageRequest(AIModel):
    message: str = Field(min_length=1, max_length=4096)

