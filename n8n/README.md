# Phase 6 n8n workflow

`phase-6-whatsapp-booking-orchestration.workflow.json` is a sanitized, inactive portfolio workflow.

It uses only environment placeholders:

- `FASTAPI_BASE_URL` — for example `http://127.0.0.1:8000`

The export contains no credentials, tokens, phone numbers, personal email addresses, credential IDs, webhook IDs, pin data or execution data. It does not call Meta, Google Sheets, Google Calendar, Gmail or Gemini directly. Python/FastAPI remains authoritative for AI routing, booking status, idempotency, mock Sheets synchronization and manager handoff.

The workflow has two synthetic local entry points:

1. Message processing → FastAPI orchestration → result routing.
2. Confirmed booking fulfillment → FastAPI → mock Sheets + one mock customer notification.

Keep the workflow inactive until a later separately approved local verification.
