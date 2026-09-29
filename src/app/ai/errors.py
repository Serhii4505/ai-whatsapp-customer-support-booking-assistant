"""Stable knowledge and AI boundary errors."""


class AIServiceError(RuntimeError):
    """Base error for controlled AI processing."""


class KnowledgeBaseError(AIServiceError):
    """Raised when the approved knowledge base is invalid."""


class ProviderOutputError(AIServiceError):
    """Raised when an AI provider returns invalid structured data."""

