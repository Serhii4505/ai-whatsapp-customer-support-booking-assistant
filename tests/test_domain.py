from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain import (
    Booking,
    BookingRequest,
    BookingRequestStatus,
    BookingStatus,
    Conversation,
    ConversationStatus,
    DEMO_SERVICES,
)


NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def test_exactly_three_valid_demo_services_exist() -> None:
    assert len(DEMO_SERVICES) == 3
    assert len({service.service_id for service in DEMO_SERVICES}) == 3
    assert all(service.active for service in DEMO_SERVICES)


def test_booking_request_requires_timezone_aware_times() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        BookingRequest(
            conversation_id=uuid4(),
            service_id="INTRO_CALL",
            requested_start=NOW.replace(tzinfo=None),
            requested_end=(NOW + timedelta(minutes=30)).replace(tzinfo=None),
            expires_at=NOW + timedelta(minutes=10),
        )


def test_confirmed_request_requires_explicit_customer_confirmation() -> None:
    with pytest.raises(ValidationError, match="explicit customer confirmation"):
        BookingRequest(
            conversation_id=uuid4(),
            service_id="INTRO_CALL",
            requested_start=NOW,
            requested_end=NOW + timedelta(minutes=30),
            expires_at=NOW + timedelta(minutes=10),
            status=BookingRequestStatus.CONFIRMED,
            customer_confirmed=False,
        )


def test_confirmed_booking_requires_calendar_reference() -> None:
    with pytest.raises(ValidationError, match="calendar event reference"):
        Booking(
            request_id=uuid4(),
            idempotency_key="booking-confirm-0000001",
            status=BookingStatus.CONFIRMED,
            created_at=NOW,
        )


def test_handoff_state_must_be_explicit() -> None:
    with pytest.raises(ValidationError, match="handed_off must be true"):
        Conversation(
            contact_id=uuid4(),
            status=ConversationStatus.HANDED_OFF,
            handed_off=False,
            created_at=NOW,
            updated_at=NOW,
        )

