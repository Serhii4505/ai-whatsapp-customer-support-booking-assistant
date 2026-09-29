import json
from pathlib import Path

import pytest

from app.calendar.definition import load_calendar_definition
from app.calendar.errors import InvalidCalendarResponseError


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "demo" / "calendar.json"


def test_demo_calendar_is_approved_and_uses_warsaw_time() -> None:
    definition = load_calendar_definition(CALENDAR_PATH)
    assert definition.calendar_id == "northstar-demo-calendar"
    assert definition.company == "Northstar Service Studio"
    assert definition.timezone == "Europe/Warsaw"
    assert definition.working_days == (0, 1, 2, 3, 4)
    assert str(definition.opens_at) == "09:00:00"
    assert str(definition.closes_at) == "17:00:00"


def test_unapproved_or_wrong_timezone_calendar_is_rejected(tmp_path: Path) -> None:
    raw = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    raw["approved"] = False
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(InvalidCalendarResponseError):
        load_calendar_definition(path)

    raw["approved"] = True
    raw["timezone"] = "UTC"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(InvalidCalendarResponseError):
        load_calendar_definition(path)

