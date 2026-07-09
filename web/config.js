// Local dev override. In the container the gateway serves a dynamic /config.js
// that sets these for you (BACKEND_URL="" = same origin). This static file is
// only used when the UI is served separately (e.g. `python3 -m http.server`).
//
// BACKEND_URL: where the gateway is. "" = same origin (when the gateway serves
// this page, which it does at http://localhost:8000).
window.BACKEND_URL = 'http://localhost:8000';

// Where the workflowId pill links (Temporal Web UI).
//   Local dev server:  http://localhost:8233/namespaces/default
//   Temporal Cloud:    https://cloud.temporal.io/namespaces/<namespace>.<account-id>
window.TEMPORAL_UI_BASE = 'http://localhost:8233/namespaces/default';

// Provider shown in the API-status panel. The gateway's dynamic /config.js
// overrides these from its env; these are just the local-static-server defaults.
window.LLM_PROVIDER = 'anthropic';
window.LLM_MODEL = 'claude-sonnet-4-6';
