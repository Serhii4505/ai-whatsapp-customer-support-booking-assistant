"""Strict IANA local-time conversion including DST gap/fold detection."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.calendar.errors import AmbiguousLocalTimeError, NonexistentLocalTimeError


def strict_local_datetime(day: date, wall_time: time, zone: ZoneInfo) -> datetime:
    """Create an aware local datetime, rejecting DST gaps and ambiguous folds."""

    naive = datetime.combine(day, wall_time)
    fold_zero = naive.replace(tzinfo=zone, fold=0)
    fold_one = naive.replace(tzinfo=zone, fold=1)

    def round_trips(candidate: datetime) -> bool:
        return candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive

    valid_zero = round_trips(fold_zero)
    valid_one = round_trips(fold_one)
    if not valid_zero and not valid_one:
        raise NonexistentLocalTimeError("local time does not exist because of a DST transition")
    if valid_zero and valid_one and fold_zero.utcoffset() != fold_one.utcoffset():
        raise AmbiguousLocalTimeError("local time is ambiguous because of a DST transition")
    return fold_zero if valid_zero else fold_one

