"""Load and validate the approved synthetic calendar definition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from app.calendar.errors import InvalidCalendarResponseError
from app.calendar.models import CalendarDefinition


def load_calendar_definition(path: Path) -> CalendarDefinition:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        definition = CalendarDefinition.model_validate(raw)
        ZoneInfo(definition.timezone)
    except (OSError, json.JSONDecodeError, ValidationError, ZoneInfoNotFoundError) as exc:
        raise InvalidCalendarResponseError("demo calendar definition is unavailable or invalid") from exc
    if definition.company != "Northstar Service Studio" or definition.timezone != "Europe/Warsaw":
        raise InvalidCalendarResponseError("demo calendar identity or timezone is invalid")
    return definition

