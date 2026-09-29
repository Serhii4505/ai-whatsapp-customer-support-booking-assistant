import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def next_weekday(day):
    candidate = day
    while candidate.weekday() > 4:
        candidate += timedelta(days=1)
    return candidate


def test_prepare_confirm_and_replay_through_api(tmp_path: Path) -> None:
    database_path = tmp_path / "assistant.sqlite3"
    settings = Settings(database_path=database_path)
    app = create_app(settings)
    conversation_id = uuid4()
    contact_id = uuid4()
    local_now = datetime.now(ZoneInfo("Europe/Warsaw"))
    target = next_weekday(local_now.date() + timedelta(days=1))

    with TestClient(app) as client:
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO contacts VALUES (?, 'Synthetic API Customer', ?, 'en', 1, ?)",
                (str(contact_id), f"synthetic-{contact_id}", local_now.isoformat()),
            )
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, 'active', 'en', 0, ?, ?)",
                (str(conversation_id), str(contact_id), local_now.isoformat(), local_now.isoformat()),
            )
        available = client.get(
            "/api/v1/availability",
            params={"service_id": "INTRO_CALL", "date": target.isoformat()},
        )
        slot_start = available.json()["slots"][0]["start"]
        prepared = client.post(
            "/api/v1/bookings/prepare",
            json={
                "conversation_id": str(conversation_id),
                "service_id": "INTRO_CALL",
                "slot_start": slot_start,
                "idempotency_key": "api-prepare-key-000001",
            },
        )
        request_id = prepared.json()["request_id"]
        confirmed = client.post(
            f"/api/v1/bookings/{request_id}/confirm",
            json={"confirmation": "confirm", "idempotency_key": "api-confirm-key-000001"},
        )
        replay = client.post(
            f"/api/v1/bookings/{request_id}/confirm",
            json={"confirmation": "confirm", "idempotency_key": "api-confirm-key-000001"},
        )

    assert available.status_code == 200
    assert prepared.status_code == 200
    assert prepared.json()["requires_explicit_confirmation"] is True
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["idempotent_replay"] is False
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["calendar_event_ref"] == confirmed.json()["calendar_event_ref"]


def test_api_requires_literal_confirmation(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "assistant.sqlite3")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/api/v1/bookings/{uuid4()}/confirm",
            json={"confirmation": "yes", "idempotency_key": "api-confirm-key-000009"},
        )
    assert response.status_code == 422

