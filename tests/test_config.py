from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_approved_defaults_are_applied(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "test.sqlite3")
    assert settings.demo_company == "Northstar Service Studio"
    assert settings.default_language == "en"
    assert settings.business_timezone == "Europe/Warsaw"
    assert {settings.whatsapp_mode, settings.calendar_mode, settings.crm_mode, settings.gemini_mode} == {"mock"}


@pytest.mark.parametrize("field", ["whatsapp_mode", "calendar_mode", "crm_mode", "gemini_mode"])
def test_phase_1_rejects_live_integration_modes(tmp_path: Path, field: str) -> None:
    values = {"database_path": tmp_path / "test.sqlite3", field: "live"}
    with pytest.raises(ValidationError, match="mock integration mode only"):
        Settings(**values)


def test_unknown_timezone_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        Settings(database_path=tmp_path / "test.sqlite3", business_timezone="Mars/Olympus")


def test_unsafe_database_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="database_path must use"):
        Settings(database_path=tmp_path / "database.txt")

