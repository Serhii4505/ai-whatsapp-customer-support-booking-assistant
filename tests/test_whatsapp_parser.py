from datetime import timezone

import pytest

from app.whatsapp.errors import InvalidWebhookPayloadError
from app.whatsapp.models import InboundKind
from app.whatsapp.parser import normalize_webhook


def payload_with(message: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "mock-account", "changes": [{"field": "messages", "value": {"messages": [message]}}]}],
    }


def test_text_message_is_normalized() -> None:
    batch = normalize_webhook(
        payload_with(
            {
                "id": "wamid.synthetic.text.001",
                "from": "48000000001",
                "timestamp": "1790683200",
                "type": "text",
                "text": {"body": "Do you have an appointment tomorrow?"},
            }
        )
    )
    message = batch.messages[0]
    assert message.kind == InboundKind.TEXT
    assert message.text == "Do you have an appointment tomorrow?"
    assert message.timestamp.tzinfo == timezone.utc


def test_unsupported_message_is_normalized_without_media_data() -> None:
    batch = normalize_webhook(
        payload_with(
            {
                "id": "wamid.synthetic.image.001",
                "from": "48000000001",
                "timestamp": "1790683200",
                "type": "image",
                "image": {"id": "untrusted-media-id", "caption": "ignored"},
            }
        )
    )
    message = batch.messages[0]
    assert message.kind == InboundKind.UNSUPPORTED
    assert message.original_type == "image"
    assert message.text is None


def test_status_only_callback_is_an_empty_batch() -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {"statuses": [{"status": "delivered"}]}}]}],
    }
    assert normalize_webhook(payload).messages == ()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"object": "another_service", "entry": []},
        {"object": "whatsapp_business_account", "entry": "not-an-array"},
        payload_with({"id": "id", "from": "48000000001", "timestamp": "bad", "type": "text", "text": {"body": "Hello"}}),
        payload_with({"id": "id", "from": "48000000001", "timestamp": "1790683200", "type": "text", "text": {"body": "  "}}),
    ],
)
def test_malformed_payloads_are_rejected(payload: object) -> None:
    with pytest.raises(InvalidWebhookPayloadError):
        normalize_webhook(payload)


@pytest.mark.parametrize(
    "timestamp",
    ["+1790683200", "1_790_683_200", "１７９０６８３２００", "-1790683200"],
)
def test_non_ascii_digit_timestamps_are_rejected(timestamp: str) -> None:
    with pytest.raises(InvalidWebhookPayloadError, match="message.timestamp is invalid"):
        normalize_webhook(
            payload_with(
                {"id": "id", "from": "48000000001", "timestamp": timestamp, "type": "text", "text": {"body": "Hello"}}
            )
        )

