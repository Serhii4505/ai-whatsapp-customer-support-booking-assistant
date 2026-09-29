"""Validated, approved knowledge-base loading and deterministic retrieval."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.errors import KnowledgeBaseError
from app.domain import DEMO_SERVICES


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {"a", "an", "and", "are", "do", "does", "for", "how", "i", "is", "of", "the", "to", "what", "you", "your"}
TOPIC_HINTS = {
    "business_hours": {"open", "opening", "hours", "working"},
    "services": {"services", "offer", "duration", "long"},
    "pricing": {"price", "pricing", "cost", "fee", "discount"},
    "booking_process": {"book", "booking", "reserve", "schedule", "confirm"},
    "changes": {"cancel", "cancellation", "reschedule", "change", "move"},
}


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BusinessFacts(KnowledgeModel):
    name: str = Field(min_length=1, max_length=120)
    language: str = Field(pattern=r"^[a-z]{2}$")
    timezone: str = Field(min_length=1, max_length=64)
    approved: bool


class ServiceFact(KnowledgeModel):
    service_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,31}$")
    name: str = Field(min_length=2, max_length=80)
    aliases: tuple[str, ...] = Field(min_length=1, max_length=10)
    duration_minutes: int = Field(ge=15, le=240, multiple_of=15)
    description: str = Field(min_length=10, max_length=500)
    approved: bool


class FAQFact(KnowledgeModel):
    source_id: str = Field(pattern=r"^faq-[a-z0-9-]{3,60}$")
    topic: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    keywords: tuple[str, ...] = Field(min_length=1, max_length=20)
    answer: str = Field(min_length=10, max_length=1000)
    approved: bool


class KnowledgeDocument(KnowledgeModel):
    business: BusinessFacts
    services: tuple[ServiceFact, ...] = Field(min_length=3, max_length=3)
    faq: tuple[FAQFact, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_approved_and_consistent(self) -> "KnowledgeDocument":
        if not self.business.approved or not all(item.approved for item in (*self.services, *self.faq)):
            raise ValueError("all knowledge entries must be explicitly approved")
        service_ids = [item.service_id for item in self.services]
        if len(set(service_ids)) != len(service_ids):
            raise ValueError("service IDs must be unique")
        source_ids = [item.source_id for item in self.faq]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("FAQ source IDs must be unique")
        expected = {item.service_id: item.duration_minutes for item in DEMO_SERVICES}
        actual = {item.service_id: item.duration_minutes for item in self.services}
        if actual != expected:
            raise ValueError("knowledge services must match the approved demo catalogue")
        return self


class RetrievedFact(KnowledgeModel):
    source_id: str
    answer: str
    score: float = Field(ge=0.0, le=1.0)


def tokenize(text: str) -> set[str]:
    return {token for token in TOKEN_PATTERN.findall(text.lower()) if token not in STOP_WORDS}


class ApprovedKnowledgeBase:
    def __init__(self, document: KnowledgeDocument) -> None:
        self.document = document
        self.service_ids = frozenset(service.service_id for service in document.services)

    @classmethod
    def load(cls, path: Path) -> "ApprovedKnowledgeBase":
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
            document = KnowledgeDocument.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise KnowledgeBaseError("approved knowledge base is unavailable or invalid") from exc
        return cls(document)

    def resolve_service(self, text: str) -> str | None:
        normalized = " ".join(text.lower().split())
        matches: list[str] = []
        for service in self.document.services:
            candidates = (service.name.lower(), *(alias.lower() for alias in service.aliases))
            if any(candidate in normalized for candidate in candidates):
                matches.append(service.service_id)
        return matches[0] if len(set(matches)) == 1 else None

    def retrieve_faq(self, query: str) -> RetrievedFact | None:
        query_tokens = tokenize(query)
        if not query_tokens:
            return None
        scored: list[RetrievedFact] = []
        for fact in self.document.faq:
            knowledge_tokens = tokenize(" ".join((fact.topic, *fact.keywords)))
            overlap = len(query_tokens & knowledge_tokens)
            if overlap:
                base_score = overlap / max(1, min(3, len(knowledge_tokens)))
                topic_bonus = 0.34 if query_tokens & TOPIC_HINTS.get(fact.topic, set()) else 0.0
                score = min(1.0, base_score + topic_bonus)
                scored.append(RetrievedFact(source_id=fact.source_id, answer=fact.answer, score=score))
        return max(scored, key=lambda item: (item.score, item.source_id)) if scored else None
