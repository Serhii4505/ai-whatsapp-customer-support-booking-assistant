from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from app.calendar.errors import AmbiguousLocalTimeError, NonexistentLocalTimeError
from app.calendar.timezone import strict_local_datetime


WARSAW = ZoneInfo("Europe/Warsaw")


def test_normal_warsaw_time_is_localized() -> None:
    value = strict_local_datetime(date(2026, 9, 30), time(9, 0), WARSAW)
    assert value.isoformat() == "2026-09-30T09:00:00+02:00"


def test_spring_dst_gap_is_rejected() -> None:
    with pytest.raises(NonexistentLocalTimeError):
        strict_local_datetime(date(2026, 3, 29), time(2, 30), WARSAW)


def test_autumn_dst_fold_is_rejected() -> None:
    with pytest.raises(AmbiguousLocalTimeError):
        strict_local_datetime(date(2026, 10, 25), time(2, 30), WARSAW)

