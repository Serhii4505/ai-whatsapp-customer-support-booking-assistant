# Phase 5 Implementation Report

Project: **AI WhatsApp Customer Support & Booking Assistant**  
Demo company: **Northstar Service Studio**  
Date: **2026-09-29**  
Status: **Complete — awaiting Sergey’s acceptance**

## Implemented

- Continued the accepted Phase 1–4 codebase without rebuilding prior work.
- Added a Python-controlled booking state machine backed by SQLite.
- Added `POST /api/v1/bookings/prepare` for selection of an approved service and an actually available slot.
- The server derives the slot end from the approved service duration; clients cannot supply duration or end time.
- Prepared requests enter `ready_for_confirmation` and expire after 15 minutes.
- Added `POST /api/v1/bookings/{request_id}/confirm` requiring the literal value `confirm`.
- Confirmation performs an immediate second availability check.
- Added a mock event adapter with atomic overlap checking and no network access.
- Created mock events block service duration plus the required 15-minute buffer.
- Prepared and confirmed commands use scoped idempotency keys and request hashes.
- Repeated prepare returns the same request; repeated confirmation returns the same event.
- Reusing a key for a different operation or payload returns an idempotency conflict.
- A second request for an overlapping slot fails after the final recheck and cannot create another event.
- If the mock provider creates an event but its response is lost, retry locates the event by idempotency key and safely finalizes the same booking.
- Calendar unavailability, occupied slots, event-creation failure and expired confirmation are recorded as safe failure states.
- Booking request status, booking status and append-only action events are persisted in SQLite.
- Availability and booking endpoints share the same mock adapter, so newly created synthetic events immediately affect subsequent availability.

## State transitions

```text
available slot
  -> ready_for_confirmation
  -> explicit confirm
  -> pending
  -> final Calendar recheck
  -> confirmed | failed

ready_for_confirmation -> expired
```

Only Python performs these transitions. Gemini output cannot call the adapter, set a state or bypass explicit confirmation.

## Idempotency and recovery

- `messages.provider_message_id` continues to deduplicate repeated webhook deliveries.
- `idempotency_keys` protects booking preparation and confirmation commands.
- `bookings.request_id` is unique, allowing at most one booking record per prepared request.
- `bookings.idempotency_key` is unique.
- The mock Calendar adapter stores events by idempotency key and returns the existing event on an identical retry.
- A provider-response-loss simulation creates one event, raises an uncertain error, and is recovered by retry without creating a second event.
- Finalization is transactionally replay-safe and does not append a duplicate confirmation event if another worker already finalized the booking.

## Time and service validation

- Only the three approved service IDs are accepted.
- Slot start must be timezone-aware and resolve to a valid `Europe/Warsaw` wall time.
- Stored timestamps are rehydrated through `ZoneInfo('Europe/Warsaw')`, not retained as a fixed UTC offset.
- Event end is derived from the approved duration.
- Busy time includes the approved 15-minute buffer.
- Past, unavailable, off-grid, outside-hours and DST-invalid slots remain rejected by the Phase 4 engine.

## Important defect found and fixed

During testing, SQLite correctly preserved the `+02:00` offset but deserialization initially produced a fixed-offset timezone rather than the named `Europe/Warsaw` zone. This was corrected by explicitly rehydrating stored timestamps through `ZoneInfo`. The fix prevents future DST calculations from using a stale fixed offset.

## Test results

```text
79 passed, 1 warning in 0.62s
```

The 79 tests include all 70 Phase 1–4 regression tests. The only warning is the known third-party FastAPI/Starlette TestClient deprecation notice.

Verified cases include:

- preparation without event creation;
- required explicit confirmation;
- correct duration, buffer and Warsaw zone;
- final availability recheck;
- repeated prepare and repeated confirm;
- same confirmed request with another confirmation key;
- idempotency-key payload conflict;
- two requests competing for one slot;
- Calendar unavailable during confirmation;
- event creation failure before creation;
- lost response after creation and safe recovery;
- expired confirmation request;
- SQLite statuses and audit events;
- complete prepare/confirm/replay API flow;
- all Phase 1–4 regression tests.

## Acceptance criteria

| Criterion | Result |
| --- | --- |
| Safe service/date/slot selection | PASS |
| Explicit confirmation before event creation | PASS |
| Python owns all state transitions | PASS |
| Availability rechecked immediately before create | PASS |
| Double booking and repeated confirmation blocked | PASS |
| Webhook and operation retries are idempotent | PASS |
| Occupied/unavailable/create-error paths fail safely | PASS |
| Duration, buffer and Europe/Warsaw enforced | PASS |
| Status and action history stored in SQLite | PASS |
| Gemini has no booking side-effect capability | PASS |
| Mock-only and synthetic-only constraints retained | PASS |
| Full regression suite remains green | PASS |

## Files added or changed

- `src/app/booking/models.py`
- `src/app/booking/errors.py`
- `src/app/booking/adapter.py`
- `src/app/booking/repository.py`
- `src/app/booking/service.py`
- `src/app/booking/router.py`
- `tests/test_booking_service.py`
- `tests/test_booking_api.py`
- shared Calendar adapter wiring in `src/app/main.py`

## Current state

DONE: Phase 5 explicit-confirmation booking state machine implemented and tested.  
DECISIONS: Server derives all authoritative booking fields; confirmation is literal and expiring; final recheck and adapter overlap check are both mandatory; retries recover by idempotency key.  
CURRENT STATE: Safe mock booking creation is ready for review; no real event or message exists.  
NEXT STEP: Wait for explicit approval before beginning Phase 6.  
BLOCKERS: None for Phase 5.
