# Runbook: Travel Planner Agent

This runbook is for presenting the demo with the Python worker, the one tmprl-demo.cloud deploys. The [README](README.md) explains what it is and how it's built, and [TALK_TRACK.md](TALK_TRACK.md) has a word-for-word script for the same Greece trip.

## What it shows

A travel agent plans a trip in chat: it searches flights, hotels, and sights, researches a destination live on the web, builds an itinerary, and books it once the traveler confirms. The agent is a plain `while` loop in a Temporal Workflow. Every model call and tool call is an Activity, and there is no agent framework.

The demo makes three problems visible:

- **An agent chains model calls, tool calls, and people, and any of them can fail.** Kill the worker in the middle of six parallel web searches, or switch the model provider off: the searches that finished stay finished, the rest retry, and the conversation carries on. Beats 3 and 4 show it.
- **Nothing gets booked until a person says so, and that person may take a while.** The agent stops at a confirmation card and waits, holding no worker or connection. Beat 5 shows it.
- **A booking that fails halfway has to undo what it already did.** The first checkout books the flight, the hotel fails, and the checkout cancels the flight. Beat 5 shows it.

## Before you start

- **On tmprl-demo.cloud,** open the Travel Planner Agent catalog entry and press **Create crashable environment**, then **Open environment** once it shows **Running**. The catalog supplies the Anthropic key, Postgres, and the Temporal credentials. Only a crashable environment can crash its own workers; on the shared instance, the **Crash workers** button tells you to create one.
- **Locally,** install Docker, the [Temporal CLI](https://docs.temporal.io/cli), and [uv](https://docs.astral.sh/uv/). Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`; every turn calls the model, so the demo doesn't run without a key. To use OpenAI instead, set `LLM_PROVIDER=openai` and `OPENAI_API_KEY`. Live destination research uses Claude's web search tool.
- The worker and the gateway load the standard `TEMPORAL_*` variables and don't switch off the Temporal CLI config file, so keep `TEMPORAL_ADDRESS=localhost:7233` and `TEMPORAL_NAMESPACE=default` in `.env`, as the example has them.
- The repo also has TypeScript, Go, and Java workers. Only one may poll the `travel-agent` Task Queue at a time. This runbook's code links are to the Python worker.

## Start it

From the repository root:

```bash
make up
```

That starts Postgres (with the seeded catalog), a Temporal dev server, the Python worker, the gateway, and the web UI. Open http://localhost:5173 (the gateway also serves the UI at http://localhost:8000). The Temporal UI is at http://localhost:8233.

A healthy start shows "Travel Planner Agent · Powered by Temporal", a greeting ("Hi! Where would you like to travel?…"), and an **Itinerary** rail on the left that reads "empty". `make status` lists postgres, temporal, worker, gateway, and web as running. The conversation's Workflow starts with your first message, and its `workflowId:` link appears under the title.

Stay on the seeded rails: fly from New York, and use Athens, Santorini, and Mykonos, which have hotels, sights, and island flights. Flights take whatever date you ask for. Research works for any place, because it's live web search.

## The walkthrough

Put the chat and the Temporal UI side by side. Each beat takes a minute or two; the research beat takes longer.

### 1. One turn of the loop

1. Type *"Find me flights from New York to Athens on October 3rd."* and press `Enter`.
2. The agent answers with flights. Click the `workflowId:` link under the title to open the conversation in the Temporal UI.
3. In the history, point out the `send_message` Update, a `call_llm` Activity, an `execute_tool` Activity with the summary `search_flights`, and a second `call_llm` that wrote the answer.
4. Say: "The model decided to call the flight search, read the result, and answered. That's one turn of the loop. The loop is the Workflow, and the model call and the tool call are each an Activity, so all of it is in this history."

### 2. The loop iterates, and the itinerary is Workflow state

1. Type *"Now find a well-located 4-star hotel in Athens for four nights, and a couple of must-see sights."* The agent calls `search_hotels` and `search_attractions` in the same turn.
2. Type *"Perfect, add those to my itinerary."* The flight, the hotel, and the sights appear in the **Itinerary** rail with a total.
3. Say: "One sentence turned into several tool calls, and I never told it the order. The itinerary isn't in a database or a cart table; it's a list in the Workflow. If the worker died now, it would come back exactly like this."

### 3. Deep research in parallel, and a crash in the middle

1. Type *"I'm also thinking about a few extra days in the Greek islands. Do a deep dive on how to spend a few days in Santorini and Mykonos."*
2. A **Researching…** card shows three stages: **Planning searches**, **Researching the web (n/N)**, and **Writing the guide**, with the **Search plan** listed underneath. In the Temporal UI, six `web_search` Activities run at once by default. Some fail on their first attempt on purpose and retry.
3. While **Researching the web** is counting, crash the worker:
   - **On tmprl-demo.cloud:** open **Demo controls** (top right) and press **Crash workers**. It kills the worker pods; Kubernetes starts new ones.
   - **Locally:** run `make kill-worker`, wait a few seconds, then `make worker`.
4. The card stops counting and the spinner keeps going. When the worker is back, the searches that hadn't finished run again, the count resumes, and the guide arrives with its sources.
5. Say: "The searches that had finished aren't run again; their results are in the history. Only the unfinished ones retry. I didn't write any of that recovery."
6. For proof, compare the `web_search` Activities in the Temporal UI. A search the crash interrupted shows a later attempt whose last failure is a heartbeat timeout. Searches that finished before the crash weren't scheduled again.
7. Then type *"Perfect, add a few days in Santorini and Mykonos to my itinerary."* The island flights, hotels, and sights join the itinerary.

A search interrupted by the crash retries once its 30-second heartbeat timeout runs out and a worker is polling, so the count can stall for up to about half a minute.

### 4. The model provider goes down (optional)

1. Open **Demo controls** and switch off **Anthropic API** (it reads **OpenAI API** if that's the provider). The drawer says "Simulated outage on — LLM calls are retrying."
2. Send any message, such as *"What's the weather like in Santorini in late October?"* The spinner keeps going. In the Temporal UI, the `call_llm` Activity fails with `LLM provider is unavailable (simulated outage).` and retries with backoff, up to 10 seconds apart.
3. Switch **Anthropic API** back on. The next attempt succeeds and the answer arrives.
4. Say: "Rate limits and outages happen to every model provider. The model call is an Activity with a retry policy, so the agent waits it out. The model client's own retries are off, so every retry is visible here."

The switch only affects this conversation. `Esc` closes the drawer.

### 5. Book it: a person confirms, and the checkout undoes a failure

1. Type *"This looks perfect, book the whole trip."*, or press **Book trip** under the itinerary.
2. A card reads "⏸ Agent requests durable checkout" with the item count and total, and "Confirm to start CheckoutWorkflow." In the Temporal UI the Workflow is waiting; there's no Activity running.
3. Say: "It stopped and asked me. The Workflow is parked on a condition. It isn't holding a thread or a connection, and it could wait like this for a minute or a month."
4. Press **Confirm**. The Temporal UI shows a `confirm_action` Signal, then a Child Workflow, `CheckoutWorkflow`, with the ID `<conversation>-checkout-1`.
5. Open the child. It runs `book_flight` for each flight, then `book_hotel`, which fails with "Hotel booking failed — the supplier returned no availability (injected demo failure)." It then runs `cancel_flight` for each flight it booked, in reverse order.
6. Back in the chat, the agent explains that checkout stopped and the flights were cancelled. The itinerary stays as it was.
7. Say: "The agent decided what to book. The checkout is ordinary code: book in order, catch the failure, undo what finished. Temporal makes sure the undo runs even if the worker dies halfway through it."
8. Ask the agent to try again, or press **Book trip** and **Confirm** again. The second checkout books everything, and the itinerary clears.

The first checkout in each conversation fails on purpose. To show a clean booking first, start the worker with `CHECKOUT_FAIL_HOTEL=false`.

### 6. A failure it knows not to retry (optional)

1. After a successful booking, type *"Actually, add that Athens to Santorini flight again and book it."* and press **Confirm**.
2. The checkout books the flight, then `finalize_checkout` fails at once with "Booking declined — this trip already includes …", cancels the flight, and the agent explains.
3. Say: "A network blip will go away, so Temporal retries it. A duplicate booking never will, so the error is marked non-retryable and fails on the first attempt. That's one flag on the error."

## Show it in code

All links point at commit [`593b41d`](https://github.com/temporal-sa/canonical-ai-demo/commit/593b41deac5bbea81c3bbfe43d809311ac4c59f0). Open a file locally with `code -g <path>:<line>`.

### The agent is a loop in a Workflow

**When to use it:** after beat 1, or when someone asks what framework the agent uses.

**Where it is:** [`python/workflows/agent.py` lines 131–169](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L131-L169) (`code -g python/workflows/agent.py:131`)

```python
while True:
    # 01 RECEIVE INPUT — wait for a chat message. The send_message update
    # drops it in and flips this flag to wake us up.
    await workflow.wait_condition(lambda: self.turn_in_progress)

    while True:
        # 02 PLAN — ask the LLM what to do next. It runs as an Activity, so
        # Temporal retries it if the provider is down (see _think).
        response = await self._think()
        self.messages.append(response.message)

        # No tool call means the LLM gave its final answer → turn is done.
        if not response.message.tool_calls:
            break

        # 03 EXECUTE TOOLS — run each tool the LLM asked for. ...
        final_answer: str | None = None
        for call in response.message.tool_calls:
            outcome = await self._dispatch(call)
            self.messages.append(
                ChatMessage(role="tool", content=outcome.result, tool_call_id=call.id)
            )
            if outcome.terminal:
                final_answer = outcome.assistant_text

        # 04 PERSIST STATE — nothing to do here. self.messages and
        # self.itinerary are workflow state; Temporal saves them for you.
        # ...
        if final_answer is not None:
            self.messages.append(ChatMessage(role="assistant", content=final_answer))
            break

    self.phase = "idle"
    self.turn_in_progress = False
```

**What you need to understand:**

- This is the whole ReAct loop: wait for a message, ask the model, run the tools it asked for, repeat until it answers with no tool call.
- A message arrives as the `send_message` Update ([lines 218–233](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L218-L233)). The Update appends the message, wakes the loop, and returns when the turn ends or pauses for approval, so the gateway gets the reply in one call.
- The conversation is `self.messages`, a list in the Workflow. There is no session store. After a crash, the new worker replays the history and rebuilds the list.
- `_dispatch` runs tools by behavior: plain tools run as an `execute_tool` Activity, and the few listed in `self._handlers` (research, itinerary, booking, invoice) get their own handler. A new plain tool needs no change here.
- A long-lived conversation would eventually need Continue-As-New to keep its history bounded; this demo's conversations are short and don't use it.

**Docs:** [Workflows](https://docs.temporal.io/workflows), [Message passing](https://docs.temporal.io/encyclopedia/workflow-message-passing)

### Retries you don't write, and errors you don't retry

**When to use it:** during beat 4 or beat 6, or when someone asks how the agent survives a flaky provider.

**Where it is:** [`python/workflows/agent.py` lines 55–71](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L55-L71) (`code -g python/workflows/agent.py:55`), with the provider's fatal errors in [`python/activities/llm.py` lines 74–76](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/activities/llm.py#L74-L76)

```python
# Retry policies. Temporal retries a failed Activity for you — no try/except
# needed. maximum_attempts is unset, so it retries forever with backoff: a
# transient outage (rate limit, DB down) just waits and recovers on its own.
# The listed error types are permanent failures retrying can't fix, so they
# stop immediately instead.
LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    non_retryable_error_types=["LLMFatalError"],
)
TOOL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    non_retryable_error_types=["BookingDeclined"],
)
```

```python
except (anthropic.BadRequestError, anthropic.AuthenticationError,
        anthropic.PermissionDeniedError, anthropic.NotFoundError) as e:
    raise ApplicationError(f"LLM request rejected: {e}", type="LLMFatalError", non_retryable=True) from e
```

**What you need to understand:**

- Retries start at 1 second and double up to 10 seconds, with no attempt limit. A 10-second cap keeps recovery quick to watch; the default cap is 100 seconds.
- The Anthropic and OpenAI clients are created with `max_retries=0`, so Temporal does every retry and each one is in the history.
- A rejected request (bad key, bad request, unknown model) is raised as a non-retryable `LLMFatalError`, because sending it again can't help. Rate limits and server errors are left retryable.
- Each call also has a short start-to-close timeout: 30 seconds for model calls and 15 for tools ([line 182](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L182), [line 211](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L211)). That's how Temporal notices a worker that died mid-call and retries the call elsewhere.
- If a model call fails for good, `_think` returns an apology instead of failing the Workflow, so the chat stays usable.

**Docs:** [Retry Policies](https://docs.temporal.io/encyclopedia/retry-policies), [Activity timeouts](https://docs.temporal.io/encyclopedia/detecting-activity-failures)

### Fan the research out as parallel Activities

**When to use it:** during beat 3, while the search count climbs, or right after the crash.

**Where it is:** [`python/workflows/agent.py` lines 312–327](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L312-L327) (`code -g python/workflows/agent.py:312`), with the heartbeat in [`python/activities/research.py` lines 132–136](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/activities/research.py#L132-L136)

```python
# Run all searches at once as parallel Activities. Kill the worker
# mid-search and only the unfinished ones re-run — finished ones are
# remembered. (A plain Python loop would redo them all.)
self.phase = "searching"

async def _run_search(item: SearchItem) -> str:
    result = await workflow.execute_activity(
        web_search, item,
        start_to_close_timeout=timedelta(seconds=120),
        heartbeat_timeout=timedelta(seconds=30),
        retry_policy=LLM_RETRY,
    )
    self.searches_done += 1
    return result

findings = await asyncio.gather(*[_run_search(s) for s in self.plan])
```

**What you need to understand:**

- `asyncio.gather` over Activities schedules all of them at once. The plan step decides how many; `RESEARCH_SEARCHES` sets the target (6 by default).
- A completed search's result is in the history. On replay after a crash, the Workflow gets those results back without running them, and only the unfinished ones run again.
- A web search can take a while, so it has a 2-minute start-to-close timeout and a 30-second heartbeat timeout. The Activity heartbeats between rounds with the model, so a dead worker is noticed within about 30 seconds instead of 2 minutes.
- `self.searches_done` is what the progress card shows. The UI reads it with the `research_status` Query.
- The searches also fail on purpose: see [What's demo-only](#whats-demo-only).

**Docs:** [Heartbeat timeout](https://docs.temporal.io/encyclopedia/detecting-activity-failures#heartbeat-timeout)

### Pause for a person, for as long as it takes

**When to use it:** during beat 5, while the confirmation card is up.

**Where it is:** [`python/workflows/agent.py` lines 380–386](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L380-L386) and [lines 399–405](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L399-L405) (`code -g python/workflows/agent.py:380`), with the Signal at [lines 235–239](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L235-L239)

```python
# GATED write actions: pause for the human to approve, then do the work.
async def _await_confirmation(self) -> ApprovalDecision:
    """Pause until the human decides. wait_condition is a *durable* pause — it
    survives a worker restart and costs nothing while waiting."""
    await workflow.wait_condition(lambda: self.approval is not None)
    decision, self.approval, self.pending_confirmation = self.approval, None, None
    return decision
```

```python
# Setting this parks the turn; the UI shows a Confirm button.
self.pending_confirmation = PendingConfirmation(
    action="book_trip", title="Booking approval required",
    detail=summary, amount=total,
    args={"items": [{"title": i.title, "price": i.price} for i in self.itinerary]},
)
decision = await self._await_confirmation()
```

```python
# A *signal* sends input in without waiting for a result (fire-and-forget).
@workflow.signal
def confirm_action(self, decision: ApprovalDecision) -> None:
    """The human approved or rejected the paused action (a booking/invoice)."""
    self.approval = decision
```

**What you need to understand:**

- `wait_condition` with no timeout waits until the condition is true. While it waits, no Activity or timer runs; the Workflow is just history on the Temporal Service.
- Setting `pending_confirmation` also ends the `send_message` Update, which returns `awaiting_approval`. The UI reads the card's content with the `pending_approval` Query.
- **Confirm** sends the `confirm_action` Signal with `approved: true`; **Cancel** sends `approved: false`, and the agent is told the traveler declined.
- A customer would usually add a timeout to the wait, for example to expire a quote after a day, by passing `timeout=` to `wait_condition`. This demo waits indefinitely.

**Docs:** [Sending Signals](https://docs.temporal.io/sending-messages#sending-signals), [Python message passing](https://docs.temporal.io/develop/python/workflows/message-passing)

### The itinerary is a list in the Workflow

**When to use it:** after beat 2, when the itinerary fills in.

**Where it is:** [`python/workflows/agent.py` lines 352–363](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L352-L363) (`code -g python/workflows/agent.py:352`), declared at [lines 103–104](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L103-L104)

```python
existing = {i.item_id for i in self.itinerary}
added: list[ItineraryItem] = []
for r in rows:
    item = ItineraryItem(
        kind=r["kind"], ref_id=r["ref_id"], title=r.get("title", ""),
        subtitle=r.get("subtitle", ""), price=float(r.get("price") or 0),
    )
    if item.item_id in existing:
        continue
    self.itinerary.append(item)
    existing.add(item.item_id)
    added.append(item)
```

**What you need to understand:**

- The `execute_tool` Activity looks the items up in Postgres; the Workflow keeps the itinerary itself. There is no cart table.
- Each conversation is a new Workflow ID, so each starts with an empty itinerary and nothing leaks between sessions.
- The rail reads the itinerary with the `itinerary_view` Query, which doesn't add events to the history.
- Items are keyed by kind and catalog ID, so adding the same flight twice does nothing. Stable IDs are also what let the checkout refuse a duplicate booking.

### Book in order, and undo what finished if a step fails

**When to use it:** during beat 5, when the hotel fails and `cancel_flight` runs.

**Where it is:** [`python/workflows/checkout.py` lines 53–111](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/checkout.py#L53-L111) (`code -g python/workflows/checkout.py:53`), with its retry policy at [lines 32–38](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/checkout.py#L32-L38). The agent starts it at [`python/workflows/agent.py` lines 410–428](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/workflows/agent.py#L410-L428).

```python
CHECKOUT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=3,
    non_retryable_error_types=["HotelBookingFailed", "BookingDeclined"],
)
```

```python
try:
    # Business ordering is explicit and easy to customize: flights
    # first, then hotels, then activities.
    for kind, booking_activity in (
        ("flight", book_flight),
        ("hotel", book_hotel),
        ("activity", book_activity),
    ):
        for item in request.items:
            if item.kind != kind:
                continue
            reservation = await workflow.execute_activity(
                booking_activity,
                # ...
                retry_policy=CHECKOUT_RETRY,
                summary=f"Book {kind}: {item.title}",
            )
            reservations.append(reservation)
    # ...
except ActivityError as error:
    failure = _failure_message(error)
    compensations: list[CheckoutReservation] = []

    # Saga compensation: undo only the side effects that completed,
    # in reverse order. ...
    for reservation in reversed(reservations):
        cancel_activity_for_kind = {
            "flight": cancel_flight,
            "hotel": cancel_hotel,
            "activity": cancel_activity,
        }[reservation.kind]
        compensation = await workflow.execute_activity(
            cancel_activity_for_kind,
            reservation,
            start_to_close_timeout=timedelta(seconds=15),  # DB write; fast
            retry_policy=CHECKOUT_RETRY,
            summary=f"Cancel {reservation.kind}: {reservation.title}",
        )
        compensations.append(compensation)
```

**What you need to understand:**

- This is a saga written as a `try`/`except` and a loop. `reservations` is the list of what has been booked so far, and the `except` cancels exactly those, newest first.
- The Workflow's progress is durable, so if the worker dies between `book_flight` and `cancel_flight`, the new worker picks up at the same step and the cancellation still runs.
- Checkout steps stop after 3 attempts, unlike the agent's unlimited retries, and a hotel with no availability or a duplicate booking fails on the first attempt. A real checkout would tune these per provider.
- The agent runs the checkout as a Child Workflow with its own ID and history. The agent decides what to book; the child carries out the booking and its guarantees. A checkout that ends in compensation returns `compensated`, not an error, so the agent can explain what happened.
- The compensations here use the same retry policy as the bookings. In production, a cancellation usually needs to keep retrying until it succeeds, since giving up leaves a booking in place.

**Docs:** [Saga pattern](https://docs.temporal.io/design-patterns/saga-pattern), [Child Workflows](https://docs.temporal.io/child-workflows)

### Make each booking safe to retry

**When to use it:** when someone asks what happens if `book_flight` runs twice.

**Where it is:** [`python/activities/checkout.py` lines 32–43](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/activities/checkout.py#L32-L43) (`code -g python/activities/checkout.py:32`)

```python
def _reservation(req: CheckoutStepRequest) -> CheckoutReservation:
    # A real integration would pass this key to the provider. Deriving it from
    # stable business identifiers gives this demo the same retry-safe behavior.
    raw = f"{req.account_key}:{req.item.kind}:{req.item.ref_id}".encode()
    suffix = hashlib.sha256(raw).hexdigest()[:10].upper()
    prefix = {"flight": "FLT", "hotel": "HTL", "activity": "ACT"}[req.item.kind]
    return CheckoutReservation(
        kind=req.item.kind,
        ref_id=req.item.ref_id,
        title=req.item.title,
        reservation_id=f"{prefix}-{suffix}",
    )
```

**What you need to understand:**

- Temporal retries an Activity that fails or times out, so a booking can run more than once. The reservation ID comes from the conversation, the item kind, and the catalog ID, so a retry produces the same ID.
- With a real airline or hotel API, you'd send that key as the provider's idempotency key, so the provider recognizes the retry and doesn't book twice.

**Docs:** [Idempotency](https://docs.temporal.io/activities#idempotency)

### What's demo-only

When someone asks what they'd change for their own system, these are the parts to leave out:

- **The LLM outage switch.** [`python/activities/llm.py` lines 27–34](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/activities/llm.py#L27-L34): each model call Queries its own Workflow's `is_llm_down` flag and raises a retryable error while it's set. The switch is a Signal (`set_llm_status`).
- **Flaky web searches.** [`python/activities/research.py` lines 108–116](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/activities/research.py#L108-L116): each search's first attempt fails with probability `WEB_SEARCH_FAIL_RATE` (0.4 in `config.py`), so some retries are always visible.
- **The failing hotel.** [`python/activities/checkout.py` lines 52–62](https://github.com/temporal-sa/canonical-ai-demo/blob/593b41deac5bbea81c3bbfe43d809311ac4c59f0/python/activities/checkout.py#L52-L62): the first checkout in each conversation fails its hotel with a non-retryable `HotelBookingFailed`. `CHECKOUT_FAIL_HOTEL=false` turns it off.
- **Pacing delays.** Each tool call sleeps `TOOL_DELAY_SECONDS` (1 second) and each checkout step `CHECKOUT_STEP_DELAY_SECONDS` (1 second), so steps are visible in the timeline and there's time to kill a worker.
- **The data.** Flights, hotels, destinations, and sights are seeded in Postgres; only destination research is live. The bookings are rows in the same database.

## Reset and tear down

- **Between runs:** press **New session** (top right) and confirm. It terminates the current conversation's Workflow, clears the chat and the itinerary, and the next message starts a new Workflow. Refreshing the page doesn't reset anything: it reattaches to the running conversation.
- **To stop locally:** run `make down`. It stops the worker, the gateway, the web server, the dev server, and Postgres. The dev server keeps its data in memory, so every conversation is gone. Bookings in Postgres don't carry over between conversations either, because each conversation books under its own Workflow ID.
- **On tmprl-demo.cloud:** press **New session** before you leave, so the conversation doesn't stay open, then **Delete** on the environment card, or let it expire.

## When something goes wrong

| What you see | Likely cause | Fix |
|---|---|---|
| The first message errors, or the spinner never stops | The worker isn't running, or it can't reach the model | `make status`; start it with `make worker`. Check `/tmp/travel-worker.log` for a rejected API key (`LLMFatalError`) |
| "another SDK's worker is running" from `make worker` | A TypeScript, Go, or Java worker is polling `travel-agent` | Stop it from its folder with `make kill-worker` |
| The agent finds no flights or hotels | You're off the seeded rails | Fly from New York, and stay with Athens, Santorini, and Mykonos |
| The research count stalls after a crash | Interrupted searches wait for their 30-second heartbeat timeout | Wait up to half a minute after the worker is back |
| Every answer hangs, and the history shows `call_llm` retrying | The **Anthropic API** switch in **Demo controls** is off | Switch it back on |
| "The workers are taking a while to come back — refresh to pick up where it left off." | The UI stopped polling after about three minutes | Start the worker, then refresh; the page reattaches to the same conversation |
| **Crash workers** says "This is a shared instance" | You're on the shared deployment, not a crashable environment | Create a crashable environment from the catalog |
| The first booking always fails | `CHECKOUT_FAIL_HOTEL` defaults to on for the compensation beat | Book again, or start the worker with `CHECKOUT_FAIL_HOTEL=false` |

## Keeping this runbook current

The code links point at a fixed commit. When a linked file changes, update its link, line numbers, and snippet together. Before an event, list the linked files that have changed:

```sh
grep -oE 'blob/[0-9a-f]{40}/[^#)]+' RUNBOOK.md | sort -u | while IFS=/ read -r _ sha file; do
  git diff --quiet "$sha" HEAD -- "$file" || echo "changed since ${sha:0:7}: $file"
done
```
