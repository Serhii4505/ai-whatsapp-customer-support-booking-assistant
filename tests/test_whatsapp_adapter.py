import pytest
from pydantic import ValidationError
from datetime import datetime, timezone

from app.whatsapp.adapter import MockWhatsAppAdapter
from app.whatsapp.models import InboundKind, NormalizedInboundMessage


def test_mock_adapter_captures_message_without_network() -> None:
    adapter = MockWhatsAppAdapter()
    inbound = NormalizedInboundMessage(
        provider_message_id="wamid.synthetic.adapter.001",
        sender_id="48000000001",
        timestamp=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
        kind=InboundKind.TEXT,
        text="Synthetic inbound message",
        original_type="text",
    )
    adapter.inject_inbound(inbound)
    created = adapter.send_text("synthetic-recipient", "Your mock booking request was received.")
    assert adapter.inbox == (inbound,)
    assert adapter.outbox == (created,)
    adapter.clear()
    assert adapter.inbox == ()
    assert adapter.outbox == ()


def test_mock_adapter_rejects_blank_output() -> None:
    with pytest.raises(ValidationError):
        MockWhatsAppAdapter().send_text("synthetic-recipient", "   ")
