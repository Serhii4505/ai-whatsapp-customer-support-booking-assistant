# Phase 3 Implementation Report

Project: **AI WhatsApp Customer Support & Booking Assistant**  
Demo company: **Northstar Service Studio**  
Date: **2026-09-29**  
Status: **Complete — awaiting Sergey’s acceptance**

## Implemented

- Continued the accepted Phase 1–2 project without rebuilding prior work.
- Added an explicitly approved synthetic knowledge base for Northstar Service Studio.
- Knowledge base contains exactly the three approved services and five controlled FAQ facts.
- Knowledge loading rejects unapproved entries, duplicate IDs and any service/duration mismatch with the approved catalogue.
- Added strict structured schemas for intent, confidence, extracted fields, risk flags, routing and source IDs.
- Added deterministic mock Gemini classification with no SDK, API key, quota or network access.
- Supported intents: FAQ, availability check, booking request, booking confirmation, human handoff and unknown.
- Extracted only candidate service ID, date text, time text and manager request metadata.
- FAQ answers are copied by Python from the approved knowledge base, never authored freely by the AI provider.
- Every grounded FAQ answer includes its approved internal source ID.
- Unknown, low-confidence, complex, explicitly human-requested and insufficient-evidence questions fail closed to manager handoff.
- Prompt-injection patterns and unrecognized/invented services fail closed to manager handoff.
- Pricing knowledge explicitly states that no demo price is approved and a manager must confirm price, discount or commercial conditions.
- Added internal mock-only `POST /api/v1/ai/respond` for controlled testing.
- AI response schema forbids side effects; booking-related output routes only to a future deterministic Python flow.

## Architecture and safety boundary

```text
Customer text
  -> Mock Gemini intent/extraction (untrusted structured output)
  -> Pydantic schema validation
  -> Python safety policy
       -> approved FAQ fact
       -> future Python booking flow (no action in Phase 3)
       -> manager handoff
```

Gemini cannot:

- create, confirm, cancel or reschedule a booking;
- change any booking or conversation status;
- send a WhatsApp message;
- select an arbitrary service;
- invent a price, discount, schedule or policy;
- bypass Python policy using fields outside the schema.

## Important defect found and fixed

An initial test showed that a price question containing the generic word `appointment` could be classified as a booking request. The classifier was corrected so strong informational terms such as `price`, `cost`, `duration` and `hours` take precedence over generic booking nouns. Retrieval now uses topic-specific deterministic hints, ensuring a cost question selects `faq-pricing` instead of the general service entry.

## Test results

```text
57 passed, 1 warning in 0.54s
```

The 57 tests include all 41 Phase 1–2 regression tests. The only warning is the known third-party FastAPI/Starlette TestClient deprecation notice.

Verified cases include:

- exact three-service approved catalogue;
- rejected unapproved knowledge and catalogue mismatch;
- service alias resolution;
- approved hours and service FAQ retrieval;
- pricing response with no invented numeric price;
- booking intent with controlled service/date/time extraction;
- confirmation routing with zero side effects;
- prompt-injection handoff;
- invented VIP service handoff;
- unknown and complex question handoff;
- malformed provider schema fail-closed behavior;
- provider-hallucinated service rejection;
- API validation of blank and extra input fields;
- all Phase 1–2 configuration, persistence, webhook and mock-adapter tests.

## Acceptance criteria

| Criterion | Result |
| --- | --- |
| Approved knowledge base has three demo services | PASS |
| Customer intent and bounded fields are extracted | PASS |
| FAQ response comes only from approved facts | PASS |
| AI output is strictly schema-validated | PASS |
| Unknown/uncertain/complex requests hand off | PASS |
| Prompt injection fails closed | PASS |
| Invented services and prices are blocked | PASS |
| Mock Gemini behavior is deterministic | PASS |
| AI performs no booking or messaging side effect | PASS |
| Phase 1–2 regression suite remains green | PASS |
| Synthetic data only; no external API calls | PASS |

## Files added or changed

- `demo/knowledge_base.json`
- `src/app/ai/models.py`
- `src/app/ai/knowledge.py`
- `src/app/ai/provider.py`
- `src/app/ai/service.py`
- `src/app/ai/router.py`
- `tests/test_ai_knowledge.py`
- `tests/test_ai_service.py`
- `tests/test_ai_api.py`

## Current state

DONE: Phase 3 controlled AI and grounded knowledge layer implemented and tested.  
DECISIONS: AI output is untrusted; Python owns validation and routing; approved knowledge owns response text; unsafe/unknown cases fail closed.  
CURRENT STATE: Mock-only AI layer is ready for review and has no side-effect capability.  
NEXT STEP: Wait for explicit approval before beginning Phase 4.  
BLOCKERS: None for Phase 3.
