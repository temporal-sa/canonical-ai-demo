# web/ — the frontend **and** the gateway

This folder owns both halves of the demo's front door:

- **`gateway.py`** — the one HTTP gateway. FastAPI, 5 endpoints, each one a single Temporal
  client call (start / update / query / signal). It drives the workflow **by string names**,
  so it imports no worker code and works against *any* SDK's worker (Python today, TypeScript
  later). It also serves this UI same-origin. The endpoint list is the top of `gateway.py`.
- **`index.html` / `app.js` / `config.js`** — the chat UI (vanilla JS, no build step).

The SDK folders (`python/`, `typescript/`) stay pure Temporal — worker, workflow, activities.

## Run it

Easiest — the whole local stack from the repo root:

```bash
make up          # postgres + temporal + worker + gateway + UI
```

Then open **http://localhost:8000** (the gateway serves the UI same-origin) and
**http://localhost:8233** (the Temporal UI).

Just the gateway on its own:

```bash
cd web && uv run uvicorn gateway:app --port 8000
```

## Develop the UI with no backend (stub)

`stub-server.mjs` is a dependency-free Node server that implements the same contract with
canned replies — use it to iterate on the UI without Temporal, a worker, an LLM, or a DB.

```bash
node stub-server.mjs        # :8000, same contract, fake data
```

A message containing **"buy"** triggers the `awaiting_approval` flow so you can style the
approval card.

## Notes

- **No sign-in step.** The first message creates the workflow; the customer identity comes
  from the auth gate's verified email in cloud, or a default locally.
- **`config.js`** is the local-dev override. In the container, the gateway serves a dynamic
  `/config.js` that sets `BACKEND_URL=""` (same origin) and the right Temporal UI link.
- The **workflowId pill** under the hero links straight to this conversation's workflow in
  the Temporal UI — the "conversation ID *is* the workflow ID" beat.
