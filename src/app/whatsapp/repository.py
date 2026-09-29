"""Transactional SQLite persistence for normalized webhook messages."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.whatsapp.models import InboundKind, NormalizedInboundMessage, WebhookProcessResult


class WhatsAppRepository:
    """Persist minimal pseudonymous message data with database-backed deduplication."""

    def __init__(self, database_path: Path, pseudonym_secret: str) -> None:
        self.database_path = database_path
        self.pseudonym_secret = pseudonym_secret

    def _fingerprint(self, sender_id: str) -> str:
        return hmac.new(
            self.pseudonym_secret.encode("utf-8"),
            sender_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def process(self, messages: tuple[NormalizedInboundMessage, ...]) -> WebhookProcessResult:
        processed = 0
        duplicates = 0
        unsupported = 0

        with closing(sqlite3.connect(self.database_path, timeout=5.0)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                for message in messages:
                    sender_ref = self._fingerprint(message.sender_id)
                    contact_id = str(uuid5(NAMESPACE_URL, f"whatsapp-contact:{sender_ref}"))
                    conversation_id = str(uuid5(NAMESPACE_URL, f"whatsapp-conversation:{sender_ref}"))
                    timestamp = message.timestamp.isoformat()
                    connection.execute(
                        "INSERT OR IGNORE INTO contacts "
                        "(contact_id, display_name, external_user_ref, language, opt_in_recorded, created_at) "
                        "VALUES (?, 'WhatsApp Customer', ?, 'en', 0, ?)",
                        (contact_id, sender_ref, timestamp),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO conversations "
                        "(conversation_id, contact_id, status, language, handed_off, created_at, updated_at) "
                        "VALUES (?, ?, 'active', 'en', 0, ?, ?)",
                        (conversation_id, contact_id, timestamp, timestamp),
                    )
                    stored_text = (
                        message.text
                        if message.kind == InboundKind.TEXT
                        else f"[unsupported:{message.original_type}]"
                    )
                    message_status = "received" if message.kind == InboundKind.TEXT else "rejected"
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO messages "
                        "(message_id, conversation_id, provider_message_id, direction, status, text, received_at) "
                        "VALUES (?, ?, ?, 'inbound', ?, ?, ?)",
                        (
                            str(uuid4()),
                            conversation_id,
                            message.provider_message_id,
                            message_status,
                            stored_text,
                            timestamp,
                        ),
                    )
                    if cursor.rowcount == 0:
                        duplicates += 1
                    else:
                        processed += 1
                        if message.kind == InboundKind.UNSUPPORTED:
                            unsupported += 1

        return WebhookProcessResult(
            received=len(messages),
            processed=processed,
            duplicates=duplicates,
            unsupported=unsupported,
        )

