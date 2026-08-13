# The SDK contract

This demo is **multi-SDK**. The worker (the durable agent) can be written in any
Temporal SDK — Python today, TypeScript next — while the **gateway + web UI stay
the same**. That works because `web/gateway.py` imports **zero** worker code: it
drives the workflow purely by **string names** over the Temporal client.

This file is the spec. A worker in any language is "done" when it implements
everything below. Target *this document*, not the Python source.

> **Only one SDK's worker runs at a time.** All SDKs share the task queue
> `travel-agent` and the workflow type `TravelAgentWorkflow`. Temporal routes a
> workflow's tasks to whatever worker is polling that queue — and a history
> written by one SDK cannot be replayed by another (it would be a
> non-determinism error). So: **kill the current worker before starting another
> SDK's.** New conversations started after the switch run on the new worker.

---

## Identity

| Thing | Value | Where it's set |
|-------|-------|----------------|
| Task queue | `travel-agent` | `TASK_QUEUE` env (gateway + worker) |
| Workflow type | `TravelAgentWorkflow` | `WORKFLOW_TYPE` env (gateway); the worker registers a workflow of this exact type name |
| Start argument | a single `string` — the traveller's email | `gateway.py` → `start_workflow(WORKFLOW_TYPE, email, id=conversationId, ...)` |
| Workflow ID | `trip-<email-slug>-<hex>` = the conversation ID | minted by the gateway |

The workflow does **not** return a meaningful value — it stays alive for the
whole conversation, serving updates and queries. (Conversation = workflow
lifetime.)

---

## Handlers (the wire surface)

Names are the literal strings the gateway sends. **Match them exactly.**

### Update

| Name | Args | Returns |
|------|------|---------|
| `send_message` | `text: string` | `TurnResult` |

`TurnResult` = `{ "status": "reply" | "awaiting_approval", "reply": string }`.

A message that triggers a human-gated tool returns `status: "awaiting_approval"`
(the gateway then polls `pending_approval`); otherwise `status: "reply"` with the
assistant's text. If the update **fails** (e.g. "a turn is already in progress",
or a non-retryable business decline), raise an application error — the gateway
maps it to HTTP 409 using the failure message.

### Signals

| Name | Args |
|------|------|
| `confirm_action` | `ApprovalDecision` = `{ "approved": boolean, "reason": string \| null }` |
| `set_llm_status` | `down: boolean` — the per-conversation LLM kill-switch |

### Queries

| Name | Returns |
|------|---------|
| `is_llm_down` | `boolean` |
| `transcript` | `ChatMessage[]` — gateway reads only `role` + `content` |
| `pending_approval` | `PendingConfirmation \| null` |
| `research_status` | `ResearchStatus` |
| `itinerary_view` | `ItineraryItem[]` |

---

## Payload shapes — **snake_case on the wire**

⚠️ The gateway reads snake_case keys directly (`searches_total`, `ref_id`,
`action`, …). SDKs whose idiom is camelCase (TypeScript, Go) **must emit
snake_case** in these DTOs. This is the single most common thing to get wrong.

```jsonc
// ChatMessage — role is one of: system | user | assistant | tool
{ "role": "assistant", "content": "…" }
// (tool_calls / tool_call_id may exist internally but the gateway ignores them)

// PendingConfirmation  (or null)
{
  "action": "book_trip" | "create_invoice",
  "title":  "…",
  "detail": "…",
  "amount": 0.0,
  "args":   { }
}

// ResearchStatus
{
  "phase": "idle",                 // idle · planning · searching · writing
  "plan":  [ { "query": "…", "reason": "…" } ],
  "searches_total": 0,
  "searches_done":  0
}

// ItineraryItem
{
  "kind":     "flight" | "hotel" | "activity",
  "ref_id":   0,
  "title":    "…",
  "subtitle": "…",
  "price":    0.0
}
```

---

## Data-converter compatibility

The gateway connects with Python's **`pydantic_data_converter`**; a non-Python
worker uses its SDK's **default JSON converter**. These interoperate **because
every payload here is plain JSON** — strings, numbers, booleans, nested objects
and arrays. No `datetime`, `bytes`, `Decimal`, or other type that needs special
encoding crosses the wire. Both sides read/write the `json/plain` payload
encoding, so nothing custom is required on the non-Python side. Keep it that way:
if you ever need a richer type, serialize it to a plain JSON shape at the handler
boundary.

---

## What the gateway calls (reference)

Every endpoint in `web/gateway.py` is one client call against the handles above:

- `POST /conversations` → `start_workflow(WORKFLOW_TYPE, email, ...)`
- `POST /conversations/{id}/messages` → `execute_update("send_message", text)`
- `GET  /conversations/{id}/transcript` → `query("transcript")`
- `GET  /conversations/{id}/pending-approval` → `query("pending_approval")`
- `POST /conversations/{id}/approve` → `query("pending_approval")` then `signal("confirm_action", …)`
- `GET  /conversations/{id}/research-status` → `query("research_status")`
- `GET  /conversations/{id}/itinerary` → `query("itinerary_view")`
- `GET/POST /conversations/{id}/llm-status` → `query("is_llm_down")` / `signal("set_llm_status", down)`

---

## Per-SDK layout

Each SDK is a self-contained sibling folder implementing this contract:

```
python/       # the reference implementation (also the only one with Docker files)
typescript/   # local-runnable TS worker
web/          # gateway + UI — SDK-agnostic, shared by all
db/           # seed data — SDK-agnostic, shared by all
```

Non-Python SDKs are **local-runnable only** (no Docker, no deploy). Only `python/`
is containerized (`docker/`).
