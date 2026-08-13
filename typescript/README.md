# TypeScript SDK — runbook

A **local-runnable** port of the travel-agent worker (no Docker, no deploy —
that's Python's job). It implements the SDK contract in
[`../CONTRACT.md`](../CONTRACT.md), sharing the same gateway + web UI + Postgres
as every other SDK. **Anthropic-only** (no OpenAI provider path).

> One worker at a time. All SDKs share the task queue `travel-agent`; only one
> may poll it. `make up` refuses to start if another SDK's worker is running —
> see [Switching SDKs](#switching-sdks).

> **Status: feature-complete.** The full agent is ported — the ReAct loop in
> `src/agent.ts` plus all activities (LLM, tools, DB, research). Verified
> end-to-end against the shared gateway: plain tools, the durable itinerary,
> the human-in-the-loop booking/invoice gate, the non-retryable duplicate-booking
> decline, and the parallel research fan-out with live progress.

---

## Prerequisites

- **Node 18+** (developed on 25) + **npm**
- **Docker** — for Postgres (shared `../docker-compose.yml`)
- **[Temporal CLI](https://docs.temporal.io/cli)** — the local dev server
- **[uv](https://docs.astral.sh/uv/)** — only because the shared **gateway** (`../web/`) runs on it
- **`ANTHROPIC_API_KEY`** — in the repo-root `.env` (shared with every SDK)

## Quick start

```bash
# if another SDK's worker is running, stop it first (one at a time):
cd python && make kill-worker

cd ../typescript && make up   # npm install (first run) + full local stack on the TS worker
```

Then open:

- **chat UI** → http://localhost:5173
- **Temporal UI** → http://localhost:8233
- **gateway** → http://localhost:8000

`make down` stops everything · `make status` shows what's running.

## Make targets

| Target | What it does |
|--------|--------------|
| `make up` | Start the full local stack on the TS worker (auto-runs `deps`) |
| `make down` | Stop the worker + gateway + web + temporal + postgres |
| `make status` | What's running |
| `make worker` | Start just the TS worker (guards: refuses if another SDK's worker is up) |
| `make kill-worker` | Kill the worker — the crash-recovery beat (then `make worker`) |
| `make deps` | `npm install` |
| `make kill-db` / `make db` | Kill / restore Postgres — the retry beat |
| `make logs` | Tail worker + gateway logs (`/tmp/travel-worker-ts.log`) |

Shared infra targets live in `../make/common.mk`; this Makefile adds only the
TS-specific `worker` / `kill-worker` / `deps`.

## Run without make

```bash
npm install
npm run worker      # ts-node src/worker.ts  (needs the dev server + Postgres up)
npm run typecheck   # tsc --noEmit
```

## Configuration (repo-root `.env`)

Read by `src/config.ts` — the **same `.env`** the Python SDK uses.

| Var | Default | Notes |
|-----|---------|-------|
| `ANTHROPIC_API_KEY` | — | required |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | needs a model with web search for research |
| `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` | `localhost:7233` / `default` | Temporal Cloud via `TEMPORAL_API_KEY` or TLS cert/key |
| `DB_URL` | `postgresql://demo:demo@localhost:5432/travel` | or discrete `DB_HOST`/`DB_USER`/… |
| `RESEARCH_SEARCHES` | `6` | parallel searches per research pass |
| `WEB_SEARCH_MAX_USES` | `1` | web searches per search activity |
| `WEB_SEARCH_FAIL_RATE` | `0.3` | injected retryable failure rate in the fan-out |

`LLM_PROVIDER` is ignored here (Anthropic-only).

## Layout

```
typescript/
├── package.json · tsconfig.json
├── Makefile               # includes ../make/common.mk
└── src/
    ├── worker.ts          # entrypoint: registers workflow + activities
    ├── agent.ts           # TravelAgentWorkflow — the durable ReAct loop + HITL + fan-out
    ├── prompts.ts         # system prompt + TOOLS + research prompts/schemas
    ├── types.ts           # wire DTOs — ⚠️ query payloads use snake_case (see CONTRACT.md)
    ├── config.ts          # env reader + Temporal connections
    └── activities/
        ├── llm.ts  tools.ts  db.ts  research.ts  control.ts  index.ts
```

## Toolchain notes

- All `@temporalio/*` packages are pinned to the **same** version (`~1.22`).
- **TypeScript is pinned to `~5.6`** on purpose: `ts-node` can't run TS 7 (the
  native compiler), which `typescript@latest` now resolves to.
- Dev uses `ts-node` + `workflowsPath: require.resolve('./agent')` (the SDK
  bundles the workflow file into its V8 sandbox at worker start).
- The stable Anthropic SDK (`~0.116`) supports `output_config` (structured
  outputs), `effort`, and the `web_search_20250305` tool — no beta client needed.

## Switching SDKs

```bash
cd typescript && make kill-worker    # stop this one
cd ../python && make up               # bring up Python
```

New conversations started after the switch run on the new worker.
