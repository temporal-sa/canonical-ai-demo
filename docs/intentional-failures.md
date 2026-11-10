# Intentional failures

Every failure the demo causes on purpose: what triggers it, what you'll see, the point it makes,
and how to turn it off. The settings are environment variables, with the same names and defaults in
all four SDKs (`python/config.py`, `typescript/src/config.ts`, `go/internal/travelagent/config.go`,
`java/.../Config.java`). File references below are to the Python worker, the reference version.

| # | Failure | Triggered by | On by default | Retried? |
|---|---|---|---|---|
| 1 | [Hotel has no availability](#1-hotel-has-no-availability) | the first checkout in a conversation | yes | no: compensates |
| 2 | [Flaky web searches](#2-flaky-web-searches) | each search's first attempt, 40% chance | yes | yes |
| 3 | [LLM provider outage](#3-llm-provider-outage) | the "LLM API" switch in Demo controls | no | yes |
| 4 | [Duplicate booking declined](#4-duplicate-booking-declined) | booking an item this conversation already booked | always | no |
| 5 | [Worker crash](#5-worker-crash) | `make kill-worker`, or Crash workers in a cloud workspace | no | yes |
| 6 | [Workers scaled to zero](#6-workers-scaled-to-zero) | Scale to zero in a cloud workspace | no | waits |
| 7 | [Database down](#7-database-down) | `make kill-db` | no | yes |

Two pacing delays aren't failures but exist to make them watchable: see [Pacing](#pacing).

## 1. Hotel has no availability

- **Trigger:** the first checkout of a conversation. The flight books, then the hotel step fails with
  "Hotel booking failed — the supplier returned no availability (injected demo failure)."
  The second checkout books normally.
- **Where:** `book_hotel` in `activities/checkout.py`; `simulate_hotel_failure_for_attempt` in
  `workflows/agent.py` decides it's attempt 1 only.
- **What you see:** `book_flight` → `book_hotel` (failed) → `cancel_flight` in the checkout child's
  history. The agent explains that the flight was cancelled and nothing was charged.
- **The point:** a saga. A definite "no" from a supplier is a business answer, so it's
  non-retryable (`HotelBookingFailed`) and the workflow undoes the steps that succeeded.
- **Turn off:** `CHECKOUT_FAIL_HOTEL=false`.

## 2. Flaky web searches

- **Trigger:** each `web_search` in a deep-research pass fails its first attempt with probability
  `WEB_SEARCH_FAIL_RATE` (default 0.4). Retries always succeed, so the research still finishes.
- **Where:** `web_search` in `activities/research.py`, error type `WebSearchFlaky`.
- **What you see:** with six searches fanned out in parallel, usually two or three show attempt 2 in
  the history while the others carry on.
- **The point:** Temporal owns the retries, per Activity, with backoff. There's no retry code in the
  research function.
- **Turn off:** `WEB_SEARCH_FAIL_RATE=0`.

## 3. LLM provider outage

- **Trigger:** Demo controls → Failure injection → **LLM API** switch off. It's scoped to one
  conversation (a signal, `set_llm_status`, read back by query), so other users are unaffected.
- **Where:** `call_llm` in `activities/llm.py`, and `_guard()` in `activities/research.py` for the
  research calls; `activities/control.py` reads the switch. Error type `LLMProviderDown`, retryable.
- **What you see:** the turn waits, and the `call_llm` attempts climb in the history. Switch it back
  on and the turn finishes by itself, with no error shown to the user.
- **The point:** LLM APIs are flaky and rate-limited; as Activities they ride it out with no extra code.
- **Limit:** each LLM call gives up after 5 minutes (`LLM_BUDGET` in `workflows/agent.py`) and the
  agent apologises; the next message works once the switch is back on.
- **Turn off:** it's off until someone flips the switch.

## 4. Duplicate booking declined

- **Trigger:** booking an item this conversation has already booked, for example asking to "add
  that flight again and book it". Talk track beat 6.
- **Where:** `finalize_checkout` in `activities/checkout.py`, using `items_already_booked` in
  `activities/db.py`. Error type `BookingDeclined`, non-retryable.
- **What you see:** the agent says the item is already in the trip and won't book it twice.
- **The point:** retryable versus non-retryable. A network blip retries; a business rule fails fast.
  The difference is one flag on the error.
- **Turn off:** it's a rule, not an injection, so there's no setting.

## 5. Worker crash

- **Trigger:** locally, `make kill-worker` mid-turn, then `make worker`. In a crashable cloud
  workspace, Demo controls → **Crash workers** kills the worker pods, which restart by themselves.
- **Where:** the `kill-worker` target in `python/Makefile`; the `/demo-controls/crash-worker` route
  in `web/gateway.py`.
- **What you see:** in-flight Activities time out and run again on the new worker; finished ones
  don't. The best moment is mid-research (talk track beat 4) or mid-checkout.
- **The point:** durable execution. The history is the state, so nothing is lost and no tokens are
  spent twice.

## 6. Workers scaled to zero

- **Trigger:** Demo controls → **Scale to zero** in a crashable cloud workspace; scale back up
  from the same drawer.
- **Where:** `/demo-controls/scale-workers` and `/demo-controls/scale-up` in `web/gateway.py`.
- **What you see:** the conversation pauses, then carries on from the next step once workers return.
- **Limit:** the UI stops waiting after about 5½ minutes (`SETTLE_SECONDS` in `web/app.js`) and
  asks for a refresh; the workflow itself waits as long as it takes.

## 7. Database down

- **Trigger:** `make kill-db` (`docker kill postgres`); restore with `make db`.
- **Where:** the `kill-db` target in `make/common.mk`.
- **What you see:** tool calls that need the catalog fail and retry until Postgres is back, then the
  turn finishes. Each tool call gives up after 2 minutes (`TOOL_BUDGET`) and the agent is told.

## Pacing

Not failures, but they give you time to see one, or to cause one:

- `CHECKOUT_STEP_DELAY_SECONDS` (default 1.0): each checkout step pauses, so the saga reads step by
  step on the timeline.
- `TOOL_DELAY_SECONDS` (default 1.0): each tool call pauses, giving a window to kill a worker
  mid-call.

Set either to 0 for full speed.

## Not injected, but you may see them

Guard rails in `workflows/agent.py`, which end a turn cleanly rather than fail it:

- the 5-minute LLM budget and 2-minute tool budget (above);
- 12 steps per turn (`MAX_STEPS_PER_TURN`), then the agent asks you to narrow the request;
- an approval left for 24 hours expires as declined (`APPROVAL_TIMEOUT`);
- a message sent while an approval is pending, or while a turn is running, is rejected (HTTP 409).
