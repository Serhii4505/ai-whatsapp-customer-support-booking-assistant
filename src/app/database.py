"""SQLite initialization and health checks."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


SCHEMA_VERSION = 3

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    contact_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    external_user_ref TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL DEFAULT 'en',
    opt_in_recorded INTEGER NOT NULL DEFAULT 0 CHECK (opt_in_recorded IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL REFERENCES contacts(contact_id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    handed_off INTEGER NOT NULL DEFAULT 0 CHECK (handed_off IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    provider_message_id TEXT NOT NULL UNIQUE,
    direction TEXT NOT NULL,
    status TEXT NOT NULL,
    text TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS booking_requests (
    request_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE RESTRICT,
    service_id TEXT NOT NULL,
    requested_start TEXT NOT NULL,
    requested_end TEXT NOT NULL,
    status TEXT NOT NULL,
    customer_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (customer_confirmed IN (0, 1)),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE REFERENCES booking_requests(request_id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    calendar_event_ref TEXT UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_sources (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL UNIQUE,
    approved INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES knowledge_sources(source_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    UNIQUE(source_id, ordinal)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    action TEXT NOT NULL,
    response_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbound_messages (
    delivery_key TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL UNIQUE,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manager_handoffs (
    handoff_id TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manager_notifications (
    notification_id TEXT PRIMARY KEY,
    handoff_id TEXT NOT NULL UNIQUE REFERENCES manager_handoffs(handoff_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mock_sheet_bookings (
    booking_id TEXT PRIMARY KEY REFERENCES bookings(booking_id) ON DELETE RESTRICT,
    request_id TEXT NOT NULL UNIQUE REFERENCES booking_requests(request_id) ON DELETE RESTRICT,
    service_id TEXT NOT NULL,
    slot_start TEXT NOT NULL,
    slot_end TEXT NOT NULL,
    status TEXT NOT NULL,
    calendar_event_ref TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS booking_fulfillments (
    booking_id TEXT PRIMARY KEY REFERENCES bookings(booking_id) ON DELETE RESTRICT,
    sheet_status TEXT NOT NULL,
    notification_status TEXT NOT NULL,
    delivery_key TEXT NOT NULL UNIQUE,
    response_json TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_received
    ON messages(conversation_id, received_at);
CREATE INDEX IF NOT EXISTS idx_booking_requests_conversation
    ON booking_requests(conversation_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_entity
    ON audit_events(entity_type, entity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_workflow_status
    ON workflow_runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_fulfillment_status
    ON booking_fulfillments(sheet_status, notification_status, updated_at);
"""


class DatabaseError(RuntimeError):
    """Raised when database initialization or health checks fail."""


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(path: Path) -> None:
    """Create the database and apply the idempotent Phase 1 schema."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect(path)) as connection:
            connection.executescript(SCHEMA_SQL)
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseError("failed to initialize SQLite database") from exc


def database_health(path: Path) -> bool:
    """Check connectivity, schema version and foreign-key enforcement."""

    try:
        with closing(_connect(path)) as connection:
            result = connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        return result == (str(SCHEMA_VERSION),) and foreign_keys == (1,)
    except (OSError, sqlite3.Error):
        return False
