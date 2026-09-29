"""Policy layer that converts untrusted AI output into safe controlled results."""

from __future__ import annotations

from pydantic import ValidationError

from app.ai.knowledge import ApprovedKnowledgeBase
from app.ai.models import (
    ControlledResponse,
    CustomerIntent,
    ExtractedCustomerData,
    ResponseRoute,
    StructuredAIResult,
)
from app.ai.provider import StructuredAIProvider


class ControlledAIService:
    def __init__(
        self,
        provider: StructuredAIProvider,
        knowledge: ApprovedKnowledgeBase,
        min_confidence: float,
    ) -> None:
        self.provider = provider
        self.knowledge = knowledge
        self.min_confidence = min_confidence

    def process(self, customer_message: str) -> ControlledResponse:
        """Classify and route without creating bookings, changing state or sending messages."""

        try:
            analysis = StructuredAIResult.model_validate(self.provider.analyze(customer_message))
        except (ValidationError, TypeError, ValueError):
            return self._handoff(CustomerIntent.UNKNOWN, "invalid_ai_output")
        except Exception:
            # Provider failures must never authorize a reply or booking side effect.
            return self._handoff(CustomerIntent.UNKNOWN, "ai_provider_unavailable")

        if analysis.extracted.service_id not in self.knowledge.service_ids | {None}:
            return self._handoff(analysis.intent, "unapproved_service", analysis.extracted)
        if analysis.extracted.unrecognized_service:
            return self._handoff(analysis.intent, "unrecognized_service", analysis.extracted)
        if analysis.risk_flags:
            return self._handoff(analysis.intent, "safety_risk", analysis.extracted)
        if analysis.requires_handoff or analysis.intent in {CustomerIntent.UNKNOWN, CustomerIntent.HUMAN_HANDOFF}:
            return self._handoff(analysis.intent, "manager_review_required", analysis.extracted)
        if analysis.confidence < self.min_confidence:
            return self._handoff(analysis.intent, "low_confidence", analysis.extracted)

        if analysis.intent == CustomerIntent.FAQ:
            fact = self.knowledge.retrieve_faq(customer_message)
            if fact is None or fact.score < 0.25:
                return self._handoff(analysis.intent, "insufficient_approved_evidence", analysis.extracted)
            return ControlledResponse(
                intent=analysis.intent,
                route=ResponseRoute.GROUNDED_ANSWER,
                response_text=fact.answer,
                source_ids=(fact.source_id,),
                extracted=analysis.extracted,
                side_effects=(),
            )

        # Booking-related intents are handed to a future deterministic Python state machine.
        # This response authorizes no operation and performs no side effect.
        return ControlledResponse(
            intent=analysis.intent,
            route=ResponseRoute.PYTHON_BOOKING_FLOW,
            response_text=None,
            source_ids=(),
            extracted=analysis.extracted,
            side_effects=(),
        )

    @staticmethod
    def _handoff(
        intent: CustomerIntent,
        reason: str,
        extracted: ExtractedCustomerData | None = None,
    ) -> ControlledResponse:
        return ControlledResponse(
            intent=intent,
            route=ResponseRoute.MANAGER_HANDOFF,
            extracted=extracted or ExtractedCustomerData(),
            handoff_reason=reason,
            side_effects=(),
        )
