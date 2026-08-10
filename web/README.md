# web/ — gateway + chat UI

The HTTP gateway (`gateway.py`) and the static chat UI (`index.html`, `app.js`)
for the Travel Planner Agent.

The gateway drives the workflow by **string names** (`TravelAgentWorkflow`,
`send_message`, `approve_booking`, `research_status`, …) so it imports no worker
code and works against any SDK's worker. It also serves the UI same-origin.

```bash
cd web && uv run uvicorn gateway:app --port 8000
# → open http://localhost:8000
```

`config.js` is the local-dev fallback config; in a container the gateway serves a
dynamic `/config.js` (same-origin, correct Temporal-UI base, provider/model).
