# How the Travel Planner works, in flows

Twelve diagrams, each answering one question someone asks about this demo. They're drawn
from the Python worker (the reference implementation); see [`CONTRACT.md`](../CONTRACT.md)
for what every SDK's worker implements.

| # | Question | Flow |
|---|---|---|
| 1 | What are the moving parts? | [Architecture](#1-architecture) |
| 2 | What happens when I send a message? | [One chat turn](#2-one-chat-turn) |
| 3 | What is "the agent"? | [The agent loop](#3-the-agent-loop) |
| 4 | How does research run in parallel? | [Research fan-out](#4-research-fan-out) |
| 5 | What if the worker crashes? | [Crash recovery](#5-crash-recovery) |
| 6 | How does a human approve a booking? | [Human in the loop](#6-human-in-the-loop) |
| 7 | How does the agent hand off to a business process? | [Agent to checkout](#7-agent-to-checkout) |
| 8 | What happens when a booking step fails? | [The checkout saga](#8-the-checkout-saga) |
| 9 | When does the saga undo a step? | [Compensation rules](#9-compensation-rules) |
| 10 | What if the LLM provider goes down? | [Failure handling](#10-failure-handling) |
| 11 | How do retries avoid double-booking? | [Idempotency keys](#11-idempotency-keys) |
| 12 | How long does a conversation live? | [Conversation lifecycle](#12-conversation-lifecycle) |

## 1. Architecture

The gateway holds no state and imports no worker code. It drives the workflow by name
over the Temporal client. Everything durable lives in Temporal (the conversation,
the itinerary) or Postgres (the catalog, bookings, invoices).

```mermaid
flowchart TB
    UI["Chat UI<br/>web/index.html + app.js"] -->|HTTP| GW["Gateway<br/>web/gateway.py (FastAPI)"]
    GW -->|"start · update · signal · query"| TS[("Temporal Service<br/>event history")]
    TS <-->|"poll task queue travel-agent"| W["Worker<br/>python/worker.py"]
    subgraph W2 ["Inside the worker"]
        AW["TravelAgentWorkflow<br/>the agent loop"]
        CW["CheckoutWorkflow<br/>the booking saga"]
        ACT["Activities<br/>LLM · tools · research · booking"]
    end
    W --- W2
    ACT -->|SQL| DB[("Postgres<br/>catalog · bookings · invoices")]
    ACT -->|HTTPS| LLM["Claude or OpenAI<br/>chat · web search"]
```

## 2. One chat turn

A message is a Temporal **Update**: it goes in and the reply comes back on the same call.
The workflow keeps the conversation in its own state, so there's no session store.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Chat UI
    participant GW as Gateway
    participant WF as TravelAgentWorkflow
    participant A as Activities

    UI->>GW: POST /conversations/{id}/messages
    GW->>WF: update send_message(text)
    Note over WF: validator: reject if a turn is running<br/>or an approval is pending (409)
    WF->>WF: append user message, wake the loop
    loop until the LLM answers without a tool call
        WF->>A: call_llm(messages)
        A-->>WF: tool calls, or a final answer
        WF->>A: execute_tool(call) for each tool
        A-->>WF: tool results
    end
    WF-->>GW: TurnResult(reply)
    GW-->>UI: 200 reply
    Note over UI,WF: main: no validator, so a message sent mid-turn<br/>lands between a tool call and its result
```

## 3. The agent loop

`agent.py` is one `while` loop with numbered steps. Tools are dispatched by behaviour, so
adding a tool doesn't change the loop.

```mermaid
flowchart TD
    R["01 RECEIVE INPUT<br/>wait for send_message"] --> P["02 PLAN<br/>call_llm as an Activity"]
    P --> Q{"tool calls?"}
    Q -- no --> DONE["final answer:<br/>turn done, wait for next message"]
    Q -- yes --> D["03 EXECUTE TOOLS<br/>_dispatch each call"]
    D --> K{"tool behaviour"}
    K -- plain --> T["run execute_tool,<br/>result back to the LLM"]
    K -- gated --> G["pause for human approval<br/>book_trip · create_invoice"]
    K -- terminal --> X["output IS the answer<br/>research_destination"]
    T --> S["04 PERSIST STATE<br/>nothing to do: workflow state is durable"]
    G --> S
    S --> L{"05 LOOP<br/>step limit reached?"}
    L -- no --> P
    L -- yes --> STOP["ask the traveller to narrow it down"]
    X --> DONE
    STOP --> DONE
    DONE --> R
```

Branch only: the step limit (12 tool rounds per turn). On `main` the inner loop is unbounded.

## 4. Research fan-out

`research_destination` plans N searches, runs them as **parallel Activities**, then writes a
cited guide. The UI polls a query to draw the progress card.

```mermaid
sequenceDiagram
    autonumber
    participant WF as TravelAgentWorkflow
    participant P as plan_searches
    participant S as web_search ×N
    participant Wr as write_report
    participant UI as Chat UI

    WF->>P: research brief
    P-->>WF: search plan (6 queries)
    par each search is its own Activity
        WF->>S: search 1
        S--xWF: simulated flake (40% on attempt 1)
        WF->>S: retry with backoff
        S-->>WF: findings 1
    and
        WF->>S: search 2 … N
        S-->>WF: findings 2 … N
    end
    WF->>Wr: brief + all findings
    Wr-->>WF: markdown guide
    loop every second while the turn runs
        UI->>WF: query research_status
        WF-->>UI: phase, plan, searches_done
    end
```

## 5. Crash recovery

The workflow's progress is its event history on the Temporal Service, not the worker's
memory. A new worker replays the history and carries on from the next step.

```mermaid
sequenceDiagram
    autonumber
    participant TS as Temporal Service
    participant W1 as Worker 1
    participant W2 as Worker 2

    TS->>W1: workflow task
    W1->>TS: schedule web_search 1…6
    W1-->>TS: searches 1–4 completed
    Note over W1: killed mid-fan-out
    Note over TS: searches 5–6 time out<br/>(heartbeat 30s, attempt 30s–120s)
    W2->>TS: poll
    TS->>W2: history so far
    Note over W2: replay: searches 1–4 come from history,<br/>no new calls are made for them
    TS->>W2: retry searches 5–6
    W2-->>TS: completed
    W2->>TS: schedule write_report
```

## 6. Human in the loop

A gated tool parks the turn on a **durable wait**. It costs nothing while it waits and it
survives restarts. The Update returns early so the UI can show the approval card; the
approval itself arrives as a **Signal**.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Chat UI
    participant GW as Gateway
    participant WF as TravelAgentWorkflow

    UI->>GW: "book it"
    GW->>WF: update send_message
    WF->>WF: LLM calls book_trip
    WF->>WF: set pending_confirmation, wait_condition(approval)
    WF-->>GW: TurnResult(awaiting_approval)
    GW-->>UI: show the approval card
    UI->>GW: POST /approve
    GW->>WF: query pending_approval
    GW->>WF: signal confirm_action(approved)
    Note over WF: ignored if nothing is pending
    WF->>WF: wait ends, turn resumes
    loop until a new reply lands
        UI->>GW: GET transcript + pending-approval
    end
    Note over WF: unanswered for 24h: expires as declined
```

Branch only: the guarded signal and the 24-hour expiry. On `main` a stray `confirm_action`
stays in state and approves the next gated action.

## 7. Agent to checkout

The agent decides **what** to book. A child workflow owns **how**: ordering, retries and
compensation. The child's result goes back to the LLM as an ordinary tool result.

```mermaid
sequenceDiagram
    autonumber
    participant AW as TravelAgentWorkflow
    participant CW as CheckoutWorkflow<br/>id = conversation-checkout-N
    participant LLM as call_llm

    AW->>AW: approval received, checkout_attempt += 1
    AW->>CW: start child (parent close: REQUEST_CANCEL)
    CW->>CW: book flights → hotels → activities → finalize
    CW-->>AW: CheckoutResult(booked | compensated)
    AW->>LLM: tool result = CheckoutResult
    LLM-->>AW: explains the outcome to the traveller
```

## 8. The checkout saga

The scripted demo path: the first attempt's hotel declines, so the flight is cancelled.
A second attempt books cleanly.

```mermaid
sequenceDiagram
    autonumber
    participant CW as CheckoutWorkflow
    participant F as Airline
    participant H as Hotel
    participant DB as Postgres

    rect rgba(220, 80, 80, 0.12)
    Note over CW: attempt 1
    CW->>F: book_flight(FLT-key1)
    F-->>CW: booked
    CW->>H: book_hotel(HTL-key1)
    H--xCW: HotelBookingFailed (definite no, not retried)
    CW->>F: cancel_flight(FLT-key1)
    F-->>CW: cancelled
    Note over CW: returns "compensated"
    end
    rect rgba(80, 160, 80, 0.12)
    Note over CW: attempt 2: new keys
    CW->>F: book_flight(FLT-key2)
    CW->>H: book_hotel(HTL-key2)
    CW->>DB: finalize_checkout(checkout_id)
    DB-->>CW: booking_id
    Note over CW: returns "booked"
    end
```

## 9. Compensation rules

What the saga does when a step fails. A **definite no** left nothing behind. An **unknown
outcome** (timed out, retries exhausted, cancelled mid-step) might have booked, and
cancelling by ID is safe either way, so it gets undone too.

```mermaid
flowchart TD
    S["register the undo for this step"] --> B["run the step<br/>up to 3 attempts"]
    B --> OK{"result"}
    OK -- succeeded --> NEXT["next step<br/>(back to the top)"]
    OK -- "definite no<br/>HotelBookingFailed · BookingDeclined" --> POP["drop this step's undo"]
    OK -- "unknown outcome<br/>timeout · retries exhausted" --> KEEP["keep this step's undo"]
    OK -- "checkout cancelled" --> KEEP
    POP --> U["run the newest remaining undo"]
    KEEP --> U
    U --> R{"undo succeeded?"}
    R -- no --> RETRY["retry with backoff,<br/>no attempt limit:<br/>visible as a pending Activity"]
    RETRY --> R
    R -- yes --> MORE{"more undos?"}
    MORE -- yes --> U
    MORE -- no --> END2["return compensated<br/>(or stay cancelled)"]
```

Branch only. On `main`: undos are registered after the step succeeds, so an unknown outcome
isn't undone; undos stop after 3 attempts; cancellation doesn't compensate.

## 10. Failure handling

Three layers. Classify what you know, retry what's transient, and bound what you don't know.
The Demo-controls LLM kill switch exercises the second layer.

```mermaid
flowchart TD
    E["an Activity fails"] --> C{"classified as permanent?<br/>LLMFatalError: bad key, bad request"}
    C -- yes --> STOP["stop at once"]
    C -- no --> RT["retry with backoff<br/>1s, 2s, 4s … capped at 10s"]
    RT --> OKQ{"succeeded?"}
    OKQ -- yes --> GO["carry on"]
    OKQ -- no --> BUD{"total budget used up?<br/>LLM 5 min · tool 2 min"}
    BUD -- no --> RT
    BUD -- yes --> STOP
    STOP --> AP["the turn ends with an apology,<br/>the conversation stays usable"]
    W["worker startup"] --> KEY{"chat provider key set?"}
    KEY -- no --> REFUSE["refuse to start"]
    KEY -- yes --> POLL["poll for tasks"]
```

Branch only: the budgets and the startup check. On `main` an unclassified error (such as a
missing key) retries forever.

## 11. Idempotency keys

Every key is derived from the workflow ID, so a replay or a retry produces the same key, and
the receiving system recognises the repeat.

```mermaid
flowchart LR
    CONV["conversation workflow ID<br/>trip-…-a1b2"] --> CK["checkout ID<br/>trip-…-a1b2-checkout-N"]
    CONV --> INV["invoice key<br/>trip-…-a1b2-invoice-N"]
    CK --> RES["reservation IDs<br/>FLT-/HTL-/ACT- + hash(checkout ID, item)"]
    CK --> BK["booking record<br/>booking.checkout_id (UNIQUE)"]
    RES -->|"sent to the supplier"| SUP["airline · hotel · attraction"]
    BK -->|"retry returns the existing booking"| DB[("Postgres")]
    INV -->|"retry returns the existing invoice"| DB
```

Branch only. On `main`: reservation IDs hash the conversation (not the checkout), so a second
attempt reuses a cancelled reservation's ID; bookings and invoices have no key, and a
retried finalize can decline its own booking as a duplicate.

## 12. Conversation lifecycle

One conversation is one workflow ID. Its history is kept short by continuing-as-new between
turns, and it closes itself once idle.

```mermaid
stateDiagram-v2
    [*] --> Idle: gateway starts the workflow
    Idle --> Turn: send_message
    Turn --> AwaitingApproval: gated tool
    AwaitingApproval --> Turn: confirm_action, or expiry after 24h
    Turn --> Idle: reply
    Idle --> ContinuedAsNew: history long
    ContinuedAsNew --> Idle: new run, same ID, state carried over
    Idle --> Closed: idle 7 days
    Turn --> Closed: terminated
    Closed --> [*]
    note right of Closed
        UI reload sees "not running"
        and starts a fresh conversation.
        A checkout still in flight
        is asked to cancel and compensates.
    end note
```

Branch only: continue-as-new, idle close and approval expiry. On `main` a conversation runs
until it's terminated, and its history grows with every turn.
