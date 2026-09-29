"""Network-free WhatsApp adapter used by Phase 2 and automated tests."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from app.whatsapp.models import MockOutboundMessage, NormalizedInboundMessage


class MockWhatsAppAdapter:
    """Capture outbound messages in memory without performing network I/O."""

    def __init__(self) -> None:
        self._inbox: list[NormalizedInboundMessage] = []
        self._outbox: list[MockOutboundMessage] = []
        self._lock = Lock()

    def inject_inbound(self, message: NormalizedInboundMessage) -> NormalizedInboundMessage:
        """Inject an already validated synthetic message without network I/O."""

        with self._lock:
            self._inbox.append(message)
        return message

    def send_text(self, recipient_ref: str, text: str) -> MockOutboundMessage:
        message = MockOutboundMessage(
            recipient_ref=recipient_ref,
            text=text,
            queued_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._outbox.append(message)
        return message

    @property
    def outbox(self) -> tuple[MockOutboundMessage, ...]:
        with self._lock:
            return tuple(self._outbox)

    @property
    def inbox(self) -> tuple[NormalizedInboundMessage, ...]:
        with self._lock:
            return tuple(self._inbox)

    def clear(self) -> None:
        with self._lock:
            self._inbox.clear()
            self._outbox.clear()
