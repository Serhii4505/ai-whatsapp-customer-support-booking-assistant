"""Defensive normalization of WhatsApp Cloud API webhook payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.whatsapp.errors import InvalidWebhookPayloadError
from app.whatsapp.models import InboundKind, NormalizedInboundMessage, WebhookBatch


def _as_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidWebhookPayloadError(f"{label} must be an object")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise InvalidWebhookPayloadError(f"{label} must be an array")
    return value


def _required_string(value: Any, label: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise InvalidWebhookPayloadError(f"{label} must be a valid string")
    return value.strip()


def _parse_timestamp(value: Any) -> datetime:
    raw = _required_string(value, "message.timestamp", max_length=16)
    # int() also accepts signs, underscores and non-ASCII digits; require plain ASCII digits.
    if not (raw.isascii() and raw.isdigit()):
        raise InvalidWebhookPayloadError("message.timestamp is invalid")
    try:
        epoch = int(raw)
        if epoch < 0:
            raise ValueError
        return datetime.fromtimestamp(epoch, timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise InvalidWebhookPayloadError("message.timestamp is invalid") from exc


def _parse_message(raw: Any) -> NormalizedInboundMessage:
    message = _as_dict(raw, "message")
    message_id = _required_string(message.get("id"), "message.id", max_length=200)
    sender_id = _required_string(message.get("from"), "message.from", max_length=64)
    message_type = _required_string(message.get("type"), "message.type", max_length=64).lower()
    timestamp = _parse_timestamp(message.get("timestamp"))

    if message_type == "text":
        text_object = _as_dict(message.get("text"), "message.text")
        text = _required_string(text_object.get("body"), "message.text.body", max_length=4096)
        kind = InboundKind.TEXT
    else:
        # Unsupported media is never downloaded or dereferenced.
        text = None
        kind = InboundKind.UNSUPPORTED

    try:
        return NormalizedInboundMessage(
            provider_message_id=message_id,
            sender_id=sender_id,
            timestamp=timestamp,
            kind=kind,
            text=text,
            original_type=message_type,
        )
    except ValidationError as exc:
        raise InvalidWebhookPayloadError("message failed validation") from exc


def normalize_webhook(payload: Any) -> WebhookBatch:
    """Normalize supported messages; accept status-only callbacks as empty batches."""

    root = _as_dict(payload, "payload")
    if root.get("object") != "whatsapp_business_account":
        raise InvalidWebhookPayloadError("unsupported webhook object")
    entries = _as_list(root.get("entry"), "payload.entry")
    normalized: list[NormalizedInboundMessage] = []

    for entry_index, entry_raw in enumerate(entries):
        entry = _as_dict(entry_raw, f"entry[{entry_index}]")
        changes = _as_list(entry.get("changes"), f"entry[{entry_index}].changes")
        for change_index, change_raw in enumerate(changes):
            change = _as_dict(change_raw, f"change[{change_index}]")
            if change.get("field") != "messages":
                continue
            value = _as_dict(change.get("value"), "change.value")
            messages = value.get("messages")
            if messages is None:
                continue
            for message_raw in _as_list(messages, "change.value.messages"):
                normalized.append(_parse_message(message_raw))

    return WebhookBatch(messages=tuple(normalized))

