"""Structured AI provider contract and deterministic Gemini mock."""

from __future__ import annotations

import re
from typing import Any, Protocol

from app.ai.knowledge import ApprovedKnowledgeBase
from app.ai.models import CustomerIntent


class StructuredAIProvider(Protocol):
    def analyze(self, message: str) -> dict[str, Any]:
        """Return untrusted structured provider output for schema validation."""


INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "reveal secret",
    "show your instructions",
    "bypass",
    "do anything now",
    "pretend you are",
)
HANDOFF_TERMS = ("human", "manager", "complaint", "refund", "legal", "custom quote", "special discount")
AVAILABILITY_TERMS = ("available", "availability", "free slot", "open slot", "appointment time")
BOOKING_TERMS = ("book", "reserve", "schedule", "appointment")
CONFIRMATION_TERMS = ("confirm", "yes, book", "yes book", "that works")
FAQ_TERMS = (
    "hours",
    "open",
    "service",
    "offer",
    "duration",
    "how long",
    "price",
    "cost",
    "fee",
    "cancel",
    "reschedule",
    "process",
)
FAQ_PRIORITY_TERMS = (
    "hours",
    "open",
    "duration",
    "how long",
    "price",
    "pricing",
    "cost",
    "fee",
    "cancel",
    "reschedule",
    "services",
    "offer",
)


class MockGeminiProvider:
    """Deterministic, network-free stand-in for structured Gemini output."""

    def __init__(self, knowledge: ApprovedKnowledgeBase) -> None:
        self.knowledge = knowledge

    def analyze(self, message: str) -> dict[str, Any]:
        normalized = " ".join(message.lower().split())
        service_id = self.knowledge.resolve_service(normalized)
        extracted: dict[str, Any] = {
            "service_id": service_id,
            "requested_date_text": self._extract_date(normalized),
            "requested_time_text": self._extract_time(normalized),
            "manager_requested": False,
            "unrecognized_service": None,
        }

        if any(pattern in normalized for pattern in INJECTION_PATTERNS):
            return self._result(CustomerIntent.HUMAN_HANDOFF, 1.0, extracted, True, ("prompt_injection",))

        if any(term in normalized for term in HANDOFF_TERMS):
            extracted["manager_requested"] = "human" in normalized or "manager" in normalized
            return self._result(CustomerIntent.HUMAN_HANDOFF, 0.99, extracted, True, ("complex_or_human_requested",))

        # Informational qualifiers take precedence over generic words such as
        # "appointment", preventing price/duration questions from entering a
        # future booking state machine.
        if any(term in normalized for term in FAQ_PRIORITY_TERMS):
            if service_id is None and self._looks_like_named_service(normalized):
                extracted["unrecognized_service"] = self._service_phrase(normalized)
            return self._result(CustomerIntent.FAQ, 0.90, extracted)

        if any(term in normalized for term in CONFIRMATION_TERMS):
            return self._result(CustomerIntent.CONFIRM_BOOKING, 0.90, extracted)

        if any(term in normalized for term in AVAILABILITY_TERMS):
            if service_id is None and self._looks_like_named_service(normalized):
                extracted["unrecognized_service"] = self._service_phrase(normalized)
            return self._result(CustomerIntent.CHECK_AVAILABILITY, 0.90, extracted)

        if any(term in normalized for term in BOOKING_TERMS):
            if service_id is None and self._looks_like_named_service(normalized):
                extracted["unrecognized_service"] = self._service_phrase(normalized)
            return self._result(CustomerIntent.BOOKING_REQUEST, 0.90, extracted)

        if any(term in normalized for term in FAQ_TERMS):
            if service_id is None and self._looks_like_named_service(normalized):
                extracted["unrecognized_service"] = self._service_phrase(normalized)
            return self._result(CustomerIntent.FAQ, 0.88, extracted)

        return self._result(CustomerIntent.UNKNOWN, 0.25, extracted, True, ("unknown_intent",))

    @staticmethod
    def _result(
        intent: CustomerIntent,
        confidence: float,
        extracted: dict[str, Any],
        requires_handoff: bool = False,
        risk_flags: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return {
            "intent": intent.value,
            "confidence": confidence,
            "extracted": extracted,
            "requires_handoff": requires_handoff,
            "risk_flags": list(risk_flags),
        }

    @staticmethod
    def _extract_date(text: str) -> str | None:
        match = re.search(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|\d{4}-\d{2}-\d{2})\b", text)
        return match.group(1) if match else None

    @staticmethod
    def _extract_time(text: str) -> str | None:
        match = re.search(r"\b(?:at\s+)?([01]?\d|2[0-3])(?::([0-5]\d))?\b", text)
        if not match:
            return None
        return f"{int(match.group(1)):02d}:{match.group(2) or '00'}"

    @staticmethod
    def _looks_like_named_service(text: str) -> bool:
        return bool(re.search(r"\b(?:vip|premium|express|emergency|custom)\s+(?:service|session|appointment|consultation)\b", text))

    @staticmethod
    def _service_phrase(text: str) -> str | None:
        match = re.search(r"\b(?:vip|premium|express|emergency|custom)\s+(?:service|session|appointment|consultation)\b", text)
        return match.group(0) if match else None
