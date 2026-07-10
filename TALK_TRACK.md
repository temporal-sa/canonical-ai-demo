# Canonical AI Agent Demo — Speaker Notes

## Overview

**What this demo is:** A single AI agent for a digital music store — it searches a
catalog, reasons over what it already knows, plans multi-step tasks, and makes purchases
with a human's approval. You'll walk the full lifecycle of an agent loop: a simple turn,
memory vs. new data, surviving a flaky LLM provider, a multi-step plan, a durable
human-in-the-loop wait, and a business failure it knows *not* to retry.

**What you're proving to the audience:** An AI agent is just a loop — the model reasons,
calls a tool, looks at the result, and repeats. That loop is fragile: it chains LLM calls,
tool calls, and human input, and any step can fail. Temporal makes the loop durable by
default, so teams stop writing retry logic and state machines and start shipping agent
features.

**Three things the audience should walk away believing:**

- **Reliability out of the box** — the agent survives a flaky LLM, a multi-day wait, and a
dead worker without re-running paid steps or losing progress. Zero recovery code.
- **Ship faster** — the whole agent is ~150 lines of ordinary Python. Retries, human-in-
the-loop, and recovery are one line each, not subsystems.
- **Full visibility** — every LLM call, tool call, and human input is one event history:
an audit log *and* the agent's memory, for free.

## Persona focused

**Business leaders**

- Modernize with agentic AI while your processes survive crashes and outages without
losing work or re-spending tokens.
- Speed up developer velocity — teams focus on business logic, not resilience plumbing.
- Full visibility into every running agent through comprehensive observability.

**Developers**

- Temporal preserves application state; your code recovers from failures and runs to
completion.
- The Temporal UI gives traceability for every call, event, and output.
- The agent loop is just code — 7 language SDKs, polyglot by design.

## Setup

- **Left screen:** the app at **[canonical-ai-demo.tmprl-demo.cloud](https://canonical-ai-demo.tmprl-demo.cloud)** — sign in
with your Google account (that's the auth gate; it also becomes your customer identity).
- **Right screen:** the **Temporal Cloud UI** for this namespace (jump to it by clicking
the **workflowId** pill in the app once a conversation starts).
- **Notice the API status panel** (bottom-right): it names the provider
(*Anthropic API · claude-sonnet-4-6*) and shows **● Operational**.
- Everything is driven from the chat. The only controls are the chat box and the API status
panel — no terminal, no kubectl required.

## Opening (~30 sec)

- Everything runs from the chat. No terminal, no kubectl.
- One-line mental model to open with:

> "An AI agent is just a loop: the model *reasons* about what to do, *calls a tool*, looks
> at the result, and repeats until it's done. That's it. What we're really here to see is
> what Temporal does *around* that loop."

## An agent is a loop (~90 sec)

- **ACTION: Type** → `Find me some AC/DC tracks`
- The agent searches the catalog and lists tracks with prices.

> "I asked in plain English. Behind the scenes the model *decided* to call a `search_music`
> tool, got rows back, and wrote that answer. Reason → act → respond. That decision wasn't
> hard-coded — the model chose the tool."

- **ACTION: Click the `workflowId` pill** → the Temporal UI opens on this conversation.

> "Here's the part that's different. This chat session is a **Temporal workflow** — a durable
> program. Every step the agent took is an **event** in this history: the model call, the
> tool call, the result. So this is your agent's reasoning trace, recorded automatically — an
> audit log you get for free, and, as we'll see, the agent's memory."

- **ACTION: Point at** the `ActivityTaskScheduled` rows — the tool name shows on the
`execute_tool` activity. *"The model calls are activities; the tools are activities; the
loop is the workflow."*

## The agent decides *when* to use a tool (~2 min)

- The point is subtle and worth teaching: an agent calls a tool only when it needs
information it doesn't already have. Do it in two small prompts.

**Needs new data → a fresh tool call**

- **ACTION: Type** → `Now find me some Queen tracks`
  - It calls `search_music` again (no Queen data) and lists them. A new tool call appears.

> "Different artist — the model doesn't have that in context, so it reaches for the search
> tool again. That's the loop turning: plan → call a tool → answer."

**Derivable from context → *no* tool call**

- **ACTION: Type** → `Which of those is the cheapest?`
  - It answers immediately — and **no** `execute_tool` event appears, only a `call_llm`.

> "Now watch — I asked which is cheapest, and it did *not* call a tool. The prices were
> already in the conversation from the search a moment ago, so it just reasoned over them.
> That conversation history *is* the agent's memory, and it's smart about not re-fetching
> what it already knows. Tools are for new information; everything else is reasoning over
> memory. And that memory is durable — it's the workflow's event history, not something in
> RAM."

## Surviving a flaky LLM — the AI beat (~2.5 min)

- In an AI app the thing that's *actually* flaky is the LLM provider — rate limits, 5xx,
timeouts. This is the beat that matters most for this audience.
- **ACTION: Click the API status panel** → it flips to **● Major outage**.
- **ACTION: Type** → `Recommend three AC/DC tracks for a first-time listener.`
  - The chat sits on *thinking…* — it does **not** answer. (This turn needs the model —
  `call_llm` — which is exactly what the outage blocks.)

> "I just simulated the LLM provider going down. In a normal agent, this is where you crash,
> or where you'd write retry logic, backoff, a dead-letter queue… Look at what our agent code
> does about it: nothing."

- **ACTION: Switch to the Temporal UI** → open this workflow → **Pending Activities**.

> "The `call_llm` activity is failing and Temporal is *retrying* it — you can see the attempt
> count climbing, with backoff. The conversation isn't broken; it's patient. I wrote one line
> — a retry policy — not a retry *loop*."

- **ACTION: Click the panel back to ● Operational.**
  - Within a few seconds the recommendation appears in the chat.

> **Key message:** "The provider came back and the next retry just succeeded. The user never
> saw an error. The unreliable parts of an agent — the model, the tools — are activities, and
> Temporal makes them retry and recover with no code from you."

## Building a multi-step plan (~2 min)

- Now escalate: one request the model has to *decompose* into several tool calls.
- **ACTION: Type** → `Put together a 5-song sampler for me — two rock tracks, two pop tracks, and one blues track.`
  - The agent decomposes it into a `search_music_by_genre` call for **rock, pop, and blues** —
  then assembles the sampler.
- **ACTION: Point at the Temporal UI** — the cluster of `execute_tool · search_music_by_genre`
events under this one `send_message` turn, one per genre.

> "One sentence from me became a plan: find something in each of three genres. Watch the
> history — several tool calls in a single turn, then the agent stitches the results into one
> answer. I didn't script 'search rock, then pop, then blues.' The model decomposed the
> request and the loop executed each step. That planning-and-acting, several steps deep, is
> the 'agent' part — and every step is a durable event you can inspect and replay."

> **Demo tip:** Adding "based on my purchase history" makes the agent also call
> `get_customer_orders` for the richer chain — but only run it that way *after* the purchase
> beat below, since a fresh conversation has no history yet (the DB is scoped per-conversation
> with no cross-session memory). Before the purchase, keep the prompt as written above.

## Waiting for a human (~2 min)

- **ACTION: Type** → `Buy those tracks for me.`
  - The agent confirms and an **Approve / Reject** card appears; the turn parks.
- **ACTION: Before clicking, switch to the Temporal UI.**

> "The agent wants to make a purchase, so it's asking a human first. The workflow is now
> **parked** — waiting on a signal. And notice in the UI it's healthy and idle: it's holding
> no thread, no connection, no memory to speak of. It could wait like this for a minute or for
> thirty days — same code, same (near-zero) cost. Try building *that* with a cron job and a
> database."

- **ACTION: Click Approve.**

> "Approving sends a **signal** into the running workflow. It wakes up exactly where it left
> off, charges the order, and confirms." (The confirmation with an invoice number lands in
> chat.)

## Knowing what *not* to retry (~90 sec)

- **ACTION: Type** → `Actually, buy the first of those three again.` *(anything you just purchased)*
- Approve it → the agent comes back with *"that was declined — you already own it."* The
conversation continues normally.

> **Key message:** "This one's a *business* failure — you can't buy a track you already own.
> Contrast it with the LLM outage: that was transient, so Temporal retried it. This one is
> **non-retryable** — retrying would never help — so Temporal doesn't. The failed step is
> still right there in the history for audit, but the agent handled it gracefully and the chat
> rolls on. Retryable vs. not is a one-word decision in the code, and Temporal respects it."

## Close (~30 sec)

> "That's the whole thing. The agent loop is about 150 lines of ordinary Python — a `while`
> loop, the model and tools as activities, a signal for the human. Everything you saw it
> survive — a flaky provider, a multi-day wait, a business rejection — it survived because
> durability is Temporal's job, not the agent's. This is the single-agent foundation;
> multi-agent and long-running memory build on exactly this."

**Three takeaways:**

- **Reliability out of the box** — the agent survived a flaky provider, a long wait, and a
business rejection without re-running paid steps.
- **Ship faster** — teams write business logic, not retry queues and state machines.
- **Full visibility** — every LLM call, event, and output in one place for understanding and
debugging.

Works with Anthropic, OpenAI, any model provider.

## Q&A ammunition

- **"Is the LLM outage fake?"** — It's a real toggle that makes the activity raise — Temporal
genuinely retries it. Same mechanism as a real rate-limit or 5xx; I just control *when* so
it fits the talk.
- **"Does the waiting cost money / hold resources?"** — No — a parked workflow holds nothing;
it's not a thread or a held connection. It wakes on the signal. That's the "wait days for
free" claim, literally.
- **"Isn't the LLM switch global — would it break other demos?"** — No, it's scoped to *this*
conversation's workflow. Two people can demo at once and only affect their own session.
- **"How do I add a tool?"** — A tool schema, one SQL function, one dispatch line — zero
workflow changes. The catalog grew from 4 tools to 8 that way.
- **"Where's the agent's memory?"** — The workflow's event history *is* the memory — no
external store, and it survives crashes and restarts.
- **"Retryable vs non-retryable?"** — Transient errors (LLM outage, network) retry
automatically; business errors (already-own) are marked non-retryable and fail fast. One
flag on the error.

## Reset between runs

- A new browser session / new conversation is a fresh workflow (the **workflowId** changes).
- Purchases are per-conversation; the API status switch is per-conversation, so it resets
when you start a new one.
- Nothing to restart between demos.

