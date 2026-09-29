from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_database_and_mock_integrations(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "assistant.sqlite3")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["company"] == "Northstar Service Studio"
    assert body["timezone"] == "Europe/Warsaw"
    assert body["data_policy"] == "synthetic_only"
    assert set(body["integrations"].values()) == {"mock"}
    assert "database_path" not in body

