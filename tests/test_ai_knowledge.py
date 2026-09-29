import json
from pathlib import Path

import pytest

from app.ai.errors import KnowledgeBaseError
from app.ai.knowledge import ApprovedKnowledgeBase


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "demo" / "knowledge_base.json"


def test_approved_knowledge_has_exactly_three_services() -> None:
    knowledge = ApprovedKnowledgeBase.load(KNOWLEDGE_PATH)
    assert knowledge.document.business.name == "Northstar Service Studio"
    assert knowledge.document.business.timezone == "Europe/Warsaw"
    assert knowledge.service_ids == {"INTRO_CALL", "STANDARD_VISIT", "EXTENDED_SESSION"}


def test_service_alias_resolution_is_controlled() -> None:
    knowledge = ApprovedKnowledgeBase.load(KNOWLEDGE_PATH)
    assert knowledge.resolve_service("Please book an intro call") == "INTRO_CALL"
    assert knowledge.resolve_service("I want a VIP service") is None


def test_retrieval_returns_approved_source() -> None:
    fact = ApprovedKnowledgeBase.load(KNOWLEDGE_PATH).retrieve_faq("What are your opening hours?")
    assert fact is not None
    assert fact.source_id == "faq-business-hours"
    assert "09:00" in fact.answer


def test_unapproved_knowledge_is_rejected(tmp_path: Path) -> None:
    raw = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    raw["faq"][0]["approved"] = False
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="unavailable or invalid"):
        ApprovedKnowledgeBase.load(path)


def test_catalogue_mismatch_is_rejected(tmp_path: Path) -> None:
    raw = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    raw["services"][0]["duration_minutes"] = 45
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(KnowledgeBaseError):
        ApprovedKnowledgeBase.load(path)

