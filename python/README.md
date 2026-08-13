# Python SDK — runbook

The **reference implementation** of the travel-agent worker, and the only SDK
that also **deploys** (see `../docker/`). It implements the SDK contract in
[`../CONTRACT.md`](../CONTRACT.md); the gateway + web UI in `../web/` are shared,
SDK-agnostic, and unchanged across SDKs.

> One worker at a time. All SDKs share the task queue `travel-agent`; only one
> SDK's worker may poll it. See [Switching SDKs](#switching-sdks).

---

## Prerequisites

- **Docker** — for Postgres (`../docker-compose.yml`)
- **[Temporal CLI](https://docs.temporal.io/cli)** — the local dev server
- **[uv](https://docs.astral.sh/uv/)** — Python deps + runner
- **`ANTHROPIC_API_KEY`** — put it in the repo-root `.env` (copy `../.env.example`)

## Quick start

```bash
cd python && make up      # postgres + temporal + python worker + gateway + web UI
```

(or just `make up` from the repo root — the root Makefile forwards to this SDK.)

Then open:

- **chat UI** → http://localhost:5173
- **Temporal UI** → http://localhost:8233
- **gateway** → http://localhost:8000

`make down` stops everything · `make status` shows what's running.

## Make targets

| Target | What it does |
|--------|--------------|
| `make up` | Start the full local stack on the Python worker |
| `make down` | Stop the worker + gateway + web + temporal + postgres |
| `make status` | What's running |
| `make worker` | Start just the Python worker (guards: refuses if another SDK's worker is up) |
| `make kill-worker` | Kill the worker — the crash-recovery beat (then `make worker`) |
| `make kill-db` / `make db` | Kill / restore Postgres — the retry beat |
| `make seed` | Regenerate `../db/seed.sql` |
| `make logs` | Tail worker + gateway logs |

Shared infra targets live in `../make/common.mk`; this Makefile adds only the
Python-specific `worker` / `kill-worker`.

## Configuration (repo-root `.env`)

Read by `config.py`. All optional except the API key.

| Var | Default | Notes |
|-----|---------|-------|
| `ANTHROPIC_API_KEY` | — | required (unless `LLM_PROVIDER=openai`) |
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `openai` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | needs a model with web search for `research_destination` |
| `OPENAI_MODEL` | `gpt-4o` | only if `LLM_PROVIDER=openai` |
| `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` | `localhost:7233` / `default` | Temporal Cloud via `TEMPORAL_API_KEY` or TLS cert/key |
| `DB_URL` | `postgresql://demo:demo@localhost:5432/travel` | or discrete `DB_HOST`/`DB_USER`/… |
| `RESEARCH_SEARCHES` | `6` | parallel searches per research pass |
| `WEB_SEARCH_MAX_USES` | `1` | web searches per search activity |
| `WEB_SEARCH_FAIL_RATE` | `0.3` | injected retryable failure rate in the fan-out |

## Layout

```
python/
├── worker.py          # entrypoint: polls travel-agent, runs workflow + activities
├── workflows/agent.py # TravelAgentWorkflow — the durable ReAct loop + HITL + fan-out
├── activities/        # llm.py · tools.py · db.py · research.py · control.py
├── prompts.py         # system prompt + TOOLS + research prompts/schemas
├── models/types.py    # pydantic models
└── config.py          # the ONE env reader
```

The agent loop in `workflows/agent.py` **is** the demo — see the root
[`../README.md`](../README.md) for the teaching narrative and how to add tools.

## Demo beats

```bash
make kill-worker   # mid-turn: the loop freezes…
make worker        #   …and resumes on the exact next step
make kill-db       # mid-turn: the tool activity retries with backoff (watch the UI)
make db            #   …and the next retry just succeeds
```

Plus the **Demo controls** drawer (top-right in the UI) → flip the **LLM API**
switch to simulate a provider outage; the turn's LLM calls retry until you flip
it back.

## Switching SDKs

Only one worker may poll `travel-agent`. To hand off to another SDK:

```bash
cd python && make kill-worker      # stop this one
cd ../typescript && make up         # bring up the other
```

New conversations started after the switch run on the new worker.

## Deploy

This SDK is containerized in `../docker/` (`worker.Dockerfile`,
`app.Dockerfile`, `postgres.Dockerfile`). Non-Python SDKs are local-only.
