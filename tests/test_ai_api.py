from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_controlled_ai_endpoint_returns_grounded_response(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "assistant.sqlite3")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/ai/respond", json={"message": "What services do you offer?"})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "grounded_answer"
    assert body["source_ids"] == ["faq-services"]
    assert body["side_effects"] == []


def test_controlled_ai_endpoint_rejects_blank_and_extra_fields(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "assistant.sqlite3")
    with TestClient(create_app(settings)) as client:
        blank = client.post("/api/v1/ai/respond", json={"message": "   "})
        extra = client.post("/api/v1/ai/respond", json={"message": "hours", "action": "book"})
    assert blank.status_code == 422
    assert extra.status_code == 422

