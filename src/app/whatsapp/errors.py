"""Stable WhatsApp boundary errors."""


class WhatsAppWebhookError(ValueError):
    """Base error for rejected webhook input."""


class InvalidSignatureError(WhatsAppWebhookError):
    """Raised when a webhook signature is missing or invalid."""


class InvalidWebhookPayloadError(WhatsAppWebhookError):
    """Raised when an incoming webhook cannot be safely normalized."""

