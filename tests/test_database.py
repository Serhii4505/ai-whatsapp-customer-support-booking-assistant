import sqlite3
from pathlib import Path

import pytest

from app.database import SCHEMA_VERSION, database_health, initialize_database


EXPECTED_TABLES = {
    "schema_meta",
    "contacts",
    "conversations",
    "messages",
    "booking_requests",
    "bookings",
    "knowledge_sources",
    "knowledge_chunks",
    "idempotency_keys",
    "audit_events",
}


def test_database_initialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "assistant.sqlite3"
    initialize_database(path)
    initialize_database(path)
    assert database_health(path)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        version = connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
    assert EXPECTED_TABLES <= tables
    assert version == (str(SCHEMA_VERSION),)


def test_provider_message_id_is_unique(tmp_path: Path) -> None:
    path = tmp_path / "assistant.sqlite3"
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?)",
            ("c1", "Synthetic Customer", "synthetic-user-001", "en", 1, "2026-09-29T12:00:00Z"),
        )
        connection.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("v1", "c1", "active", "en", 0, "2026-09-29T12:00:00Z", "2026-09-29T12:00:00Z"),
        )
        connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("m1", "v1", "wamid.synthetic.001", "inbound", "received", "Synthetic message", "2026-09-29T12:00:00Z"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("m2", "v1", "wamid.synthetic.001", "inbound", "received", "Duplicate", "2026-09-29T12:01:00Z"),
            )


def test_booking_idempotency_key_is_unique(tmp_path: Path) -> None:
    path = tmp_path / "assistant.sqlite3"
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("INSERT INTO contacts VALUES ('c1','Synthetic','synthetic-user-001','en',1,'t')")
        connection.execute("INSERT INTO conversations VALUES ('v1','c1','active','en',0,'t','t')")
        connection.execute("INSERT INTO booking_requests VALUES ('r1','v1','INTRO_CALL','s','e','confirmed',1,'x')")
        connection.execute("INSERT INTO booking_requests VALUES ('r2','v1','INTRO_CALL','s','e','confirmed',1,'x')")
        connection.execute("INSERT INTO bookings VALUES ('b1','r1','idem-0000000000001',NULL,'pending','t')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO bookings VALUES ('b2','r2','idem-0000000000001',NULL,'pending','t')")

