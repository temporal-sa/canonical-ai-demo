# Java SDK — runbook

This folder is a local-runnable Java 17 port of the durable travel agent in
[`../CONTRACT.md`](../CONTRACT.md). It implements the full gateway wire surface,
ReAct loop, durable itinerary, approval gates, parallel live research, and the
compensating child checkout workflow. It calls Anthropic's Messages API directly.

## Prerequisites

- JDK 17+ and Maven 3.9+
- Docker, Temporal CLI, and `uv` for the shared stack
- `ANTHROPIC_API_KEY` in the repository-root `.env`

Only one SDK worker may poll `travel-agent`. Stop the active SDK worker, then:

```bash
cd java
make up
```

The chat UI is at http://localhost:5173 and Temporal UI at
http://localhost:8233. `make down`, `make status`, `make kill-worker`, and
`make worker` use the shared multi-SDK targets.

Compile and test without starting infrastructure:

```bash
mvn test
```

The worker reads the shared root `.env`, including local Temporal/Postgres,
Temporal Cloud API-key auth, model/research settings, checkout failure knobs,
and `TOOL_DELAY_SECONDS`. The Java runbook does not currently configure an mTLS
client; use API-key auth for Temporal Cloud.

With `CHECKOUT_FAIL_HOTEL=true`, only the first approved checkout in an agent
session injects the hotel failure and compensation path. Later checkout attempts
in that same workflow run normally.
