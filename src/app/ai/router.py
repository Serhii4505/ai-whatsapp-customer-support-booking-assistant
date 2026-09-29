"""Internal mock-only API for controlled AI analysis."""

from __future__ import annotations

from fastapi import APIRouter

from app.ai.knowledge import ApprovedKnowledgeBase
from app.ai.models import ControlledResponse, CustomerMessageRequest
from app.ai.provider import MockGeminiProvider
from app.ai.service import ControlledAIService
from app.config import Settings


def build_ai_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/ai", tags=["controlled-ai"])
    knowledge = ApprovedKnowledgeBase.load(settings.knowledge_base_path)
    provider = MockGeminiProvider(knowledge)
    service = ControlledAIService(provider, knowledge, settings.ai_min_confidence)

    @router.post("/respond", response_model=ControlledResponse)
    def respond(request: CustomerMessageRequest) -> ControlledResponse:
        return service.process(request.message)

    return router

