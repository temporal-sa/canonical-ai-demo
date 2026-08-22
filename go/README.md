# Go SDK — runbook

This folder is a local-runnable Go port of the durable travel agent described in
[`../CONTRACT.md`](../CONTRACT.md). It implements the full gateway wire surface,
the ReAct loop, durable itinerary state, approval gates, parallel destination
research, and the compensating `CheckoutWorkflow`. The provider path is
Anthropic-only; the code uses the Messages HTTP API directly.

## Prerequisites

- Go 1.25+
- Docker, Temporal CLI, and `uv` for the shared stack
- `ANTHROPIC_API_KEY` in the repository-root `.env`

Only one SDK worker may poll `travel-agent`. Stop the current worker before
switching SDKs, then run:

```bash
cd go
make up
```

The shared chat UI is at http://localhost:5173 and Temporal UI is at
http://localhost:8233. `make down`, `make status`, `make kill-worker`, and
`make worker` behave like their Python and TypeScript counterparts.

For a build-only check:

```bash
go test ./...
```

Configuration comes from the shared root `.env`. Supported settings include
`TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY`, mTLS cert/key,
`DB_URL`, `ANTHROPIC_MODEL`, research failure knobs, checkout failure knobs, and
`TOOL_DELAY_SECONDS`.

With `CHECKOUT_FAIL_HOTEL=true`, only the first approved checkout in an agent
session injects the hotel failure and compensation path. Later checkout attempts
in that same workflow run normally.
