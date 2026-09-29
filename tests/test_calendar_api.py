from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_availability_endpoint_is_read_only_and_structured(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "assistant.sqlite3")
    today = datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat()
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/availability",
            params={"service_id": "INTRO_CALL", "date": today},
        )
        write_attempt = client.post(
            "/api/v1/availability",
            params={"service_id": "INTRO_CALL", "date": today},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["calendar_id"] == "northstar-demo-calendar"
    assert body["timezone"] == "Europe/Warsaw"
    assert body["source"] == "mock_calendar"
    assert write_attempt.status_code == 405


def test_availability_endpoint_rejects_unapproved_service(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "assistant.sqlite3")
    today = datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat()
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/v1/availability",
            params={"service_id": "VIP_SERVICE", "date": today},
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_service"
