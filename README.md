# Canonical AI Demo — a Durable Agent on Temporal

The 100-level, canonical agentic demo for the SA org. It proves one sentence:

> **The agentic ReAct loop is just a `while` loop — and Temporal makes that loop
> durable, retryable, and pausable-for-humans with essentially no extra code.**

A single support agent for the **Chinook** music store: it searches the catalog, checks a
customer's orders, and buys tracks — with a human approval gate on purchases. The LLM call
and every tool are Temporal **activities**; the agent loop is a Temporal **workflow**; the
human approval is a **signal**; the agent's memory is the **event history**.

This is the **single-agent** tier — one loop, one user, one tool set. Multi-agent, streaming,
dynamic tools, and long-horizon memory are deliberately out of scope — that's the advanced demo.

## What it demonstrates

The five primitives from the pitch deck's "Core Loop" slide, live and in ~160 lines
([`python/workflows/agent.py`](python/workflows/agent.py)):

1. **Receive input** — a message arrives via `@workflow.update`
2. **Plan** — `call_llm` activity reasons about the next action
3. **Execute tools** — `execute_tool` activity runs the chosen tool
4. **Persist state** — *nothing to write*; the history **is** the state
5. **Loop / terminate** — back to waiting for the next message

…plus the beats that make Temporal earn its place: a **simulated LLM-provider outage** (the
`call_llm` activity retries and recovers with no extra code), **crash-recovery** (kill the
worker mid-turn, it resumes on the next line), and **human-in-the-loop** (a purchase parks on
a durable `wait_condition`).

## Quick start

**Prerequisites:**

- [uv](https://docs.astral.sh/uv/)
- Docker
- the [temporal](https://docs.temporal.io/cli) CLI
- an Anthropic (or OpenAI) API key

```bash
cp .env.example .env          # then set ANTHROPIC_API_KEY=sk-ant-...
make up                       # postgres + temporal dev server + worker + gateway + web
```

Open **[http://localhost:5173](http://localhost:5173)** (the chat) and **[http://localhost:8233](http://localhost:8233)** (the Temporal UI).
Type a message — e.g. *"find me some AC/DC tracks"* — and watch the event history populate.

```bash
make status     # what's running
make down        # stop everything
make logs        # tail worker + gateway logs
```

## The demo (≈10 min)

Everything is driven from the chat — no config, no CLI. Open the chat and the Temporal UI
side by side; click the **workflowId pill** to jump to this conversation's event history.
For the full cloud walkthrough (exact prompts + what to say), see **[TALK_TRACK.md](TALK_TRACK.md)**.

1. **Happy path** — *"find me some AC/DC tracks"* → the agent searches and replies. Every
   reason-step and tool call is an event in the history — the reasoning trace, for free.
2. **Multi-step plan** — one request fans out into several tool calls in a single turn.
3. **LLM outage (the AI beat)** — flip the **API status** panel (bottom-right) to *Major
   outage*; the `call_llm` activity retries with backoff (watch the UI). Flip back → the next
   retry succeeds. No code, cloud-safe, and scoped to your conversation only.
4. **Human-in-the-loop** — ask to buy a track; the workflow parks on `wait_condition`
   (holding nothing) and the chat shows Approve/Reject. Approve → the sale completes.
5. **Unrecoverable failure (business)** — try to buy a track you **already own** → a
   *non-retryable* decline. Temporal doesn't retry it; the agent explains it and the chat
   continues. Retryable (#3) vs non-retryable (#5), side by side, is the point.

Local-only chaos moves (the cloud demo uses the API-status toggle instead):

```bash
make kill-worker && make worker   # crash-recovery: kill compute mid-turn, it resumes
make kill-db      && make db       # infra retry: kill the database, the agent waits it out
```

## Repo map

```
python/                  the agent — pure Temporal code (reference implementation)
  workflows/agent.py     ★ the ReAct loop — this file IS the demo
  activities/llm.py      call_llm — Anthropic (default) or OpenAI, one per provider
  activities/tools.py    execute_tool — dispatches the tools to db.py
  activities/db.py       plain parametrized SQL over Chinook (the data layer)
  prompts.py             the single system prompt + the tool schemas
  models/types.py        typed payloads (pydantic → readable in the Temporal UI)
  worker.py              the worker entrypoint
web/                     frontend + the ONE gateway (SDK-agnostic)
  gateway.py             FastAPI: each endpoint = one Temporal client call, driven
                         by string names — no worker code, works against any SDK
  index.html · app.js    the chat UI (vanilla JS, no build step)
db/                      vendored chinook.sql + the demo customer seed
docker/                  Dockerfiles for cloud (app=gateway / worker / postgres)
deploy/                  the DemoProject CR + how to ship to the shared cluster
Makefile                 the whole local stack: up / down / status / kill-*
```

## Add a tool (≈10 minutes, zero workflow changes)

This is the point of the architecture — new capability never touches the loop. Three edits:

1. `prompts.py` — add a tool schema to `TOOLS` (name, description, `input_schema`).
2. `activities/db.py` — add one function that runs the SQL.
3. `activities/tools.py` — add one `elif` in `execute_tool` mapping the tool name → your function.

That's it — `workflows/agent.py` is untouched. The catalog started with 4 tools; it's at 8
now (genre/artist/album search, order details) added exactly this way.

## Configuration

`config.py` is the only module that reads the environment. Local defaults just work; flip an
env var to point elsewhere — nothing else changes:


| Env var                                   | Local default                                   | Notes                                           |
| ----------------------------------------- | ----------------------------------------------- | ----------------------------------------------- |
| `ANTHROPIC_API_KEY`                       | *(required)*                                    | your key                                        |
| `LLM_PROVIDER`                            | `anthropic`                                     | or `openai`                                     |
| `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` | `localhost:7233` / `default`                    | Temporal Cloud → set these + `TEMPORAL_API_KEY` |
| `DB_URL`                                  | `postgresql://demo:demo@localhost:5432/chinook` | or discrete `DB_HOST`/`DB_PORT`/…               |
