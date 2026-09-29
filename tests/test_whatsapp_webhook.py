import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.whatsapp.security import compute_signature


SECRET = "synthetic-phase-2-secret"
TOKEN = "synthetic-phase-2-token"


def make_payload(*messages: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "mock-business-account",
                "changes": [{"field": "messages", "value": {"messages": list(messages)}}],
            }
        ],
    }


def make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    database_path = tmp_path / "assistant.sqlite3"
    settings = Settings(
        database_path=database_path,
        whatsapp_app_secret=SECRET,
        whatsapp_verify_token=TOKEN,
    )
    return TestClient(create_app(settings)), database_path


def post_signed(client: TestClient, payload: object):
    body = json.dumps(payload, separators=(",", ":")).encode()
    return client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": compute_signature(body, SECRET)},
    )


def test_webhook_challenge_success_and_failure(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    with client:
        accepted = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": TOKEN, "hub.challenge": "challenge-123"},
        )
        rejected = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "challenge-123"},
        )
    assert accepted.status_code == 200
    assert accepted.text == "challenge-123"
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["code"] == "verification_failed"


def test_valid_text_is_persisted_once_and_sender_is_pseudonymized(tmp_path: Path) -> None:
    client, database_path = make_client(tmp_path)
    payload = make_payload(
        {
            "id": "wamid.synthetic.001",
            "from": "48000000001",
            "timestamp": "1790683200",
            "type": "text",
            "text": {"body": "I would like to book a consultation."},
        }
    )
    with client:
        first = post_signed(client, payload)
        replay = post_signed(client, payload)
    assert first.status_code == 200
    assert first.json() == {"ok": True, "received": 1, "processed": 1, "duplicates": 0, "unsupported": 0}
    assert replay.json() == {"ok": True, "received": 1, "processed": 0, "duplicates": 1, "unsupported": 0}

    with sqlite3.connect(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        sender_ref = connection.execute("SELECT external_user_ref FROM contacts").fetchone()[0]
    assert count == 1
    assert sender_ref != "48000000001"
    assert len(sender_ref) == 64


def test_unsupported_message_is_recorded_without_media_fetch(tmp_path: Path) -> None:
    client, database_path = make_client(tmp_path)
    payload = make_payload(
        {
            "id": "wamid.synthetic.image.001",
            "from": "48000000001",
            "timestamp": "1790683200",
            "type": "image",
            "image": {"id": "must-not-be-fetched"},
        }
    )
    with client:
        response = post_signed(client, payload)
    assert response.status_code == 200
    assert response.json()["unsupported"] == 1
    with sqlite3.connect(database_path) as connection:
        stored = connection.execute("SELECT status, text FROM messages").fetchone()
    assert stored == ("rejected", "[unsupported:image]")


def test_missing_or_wrong_signature_is_rejected_before_processing(tmp_path: Path) -> None:
    client, database_path = make_client(tmp_path)
    body = json.dumps(make_payload()).encode()
    with client:
        missing = client.post("/webhooks/whatsapp", content=body, headers={"Content-Type": "application/json"})
        wrong = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + "0" * 64},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_invalid_json_and_schema_return_stable_errors(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    invalid_body = b"{not-json"
    with client:
        invalid_json = client.post(
            "/webhooks/whatsapp",
            content=invalid_body,
            headers={"X-Hub-Signature-256": compute_signature(invalid_body, SECRET)},
        )
        invalid_schema = post_signed(client, {"object": "wrong", "entry": []})
    assert invalid_json.status_code == 400
    assert invalid_json.json()["detail"]["code"] == "invalid_json"
    assert invalid_schema.status_code == 422
    assert invalid_schema.json()["detail"]["code"] == "invalid_webhook"


def test_oversized_payload_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "assistant.sqlite3"
    settings = Settings(
        database_path=database_path,
        whatsapp_app_secret=SECRET,
        whatsapp_verify_token=TOKEN,
        webhook_max_body_bytes=1024,
    )
    client = TestClient(create_app(settings))
    body = b"x" * 1025
    with client:
        response = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": compute_signature(body, SECRET)},
        )
    assert response.status_code == 413

