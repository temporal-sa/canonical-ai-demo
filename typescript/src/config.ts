// The ONE place that reads environment config for the TS worker — mirrors
// python/config.py so both SDKs share the same .env (and the same task queue).

import * as path from 'path';
import * as dotenv from 'dotenv';
import { NativeConnection } from '@temporalio/worker';
import { Client, Connection } from '@temporalio/client';
import { loadClientConnectConfig } from '@temporalio/envconfig';

// repo-root .env first (shared demoer quick-switch), then a local override.
dotenv.config({ path: path.resolve(__dirname, '..', '..', '.env'), override: true });
dotenv.config({ override: true });

// TEMPORAL_TASK_QUEUE is what the demo-cloud registry's crashable-workspace
// feature injects (<base>-<workspace-id>); fall back to legacy TASK_QUEUE, then
// the shared default. Mirrors python/config.py.
export const TASK_QUEUE = process.env.TEMPORAL_TASK_QUEUE ?? process.env.TASK_QUEUE ?? 'travel-agent';

// TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE and TEMPORAL_API_KEY or TEMPORAL_TLS_CLIENT_*
// env vars are loaded directly by envconfig
export const CLIENT_CONFIG = loadClientConnectConfig();

// ── Database — a full DB_URL (local docker compose) OR discrete DB_* parts. ──
function dbUrl(): string {
  if (process.env.DB_URL) return process.env.DB_URL;
  const host = process.env.DB_HOST;
  if (host) {
    const user = process.env.DB_USER ?? 'demo';
    const pw = process.env.DB_PASSWORD ?? 'demo';
    const port = process.env.DB_PORT ?? '5432';
    const name = process.env.DB_NAME ?? 'travel';
    return `postgresql://${user}:${pw}@${host}:${port}/${name}`;
  }
  return 'postgresql://demo:demo@localhost:5432/travel';
}

export const DB_URL = dbUrl();

// ── LLM provider (TS worker is Anthropic-only). ──
export const LLM_PROVIDER = process.env.LLM_PROVIDER ?? 'anthropic';
export const ANTHROPIC_MODEL = process.env.ANTHROPIC_MODEL ?? 'claude-sonnet-4-6';

// research_destination knobs — mirror python/config.py.
export const WEB_SEARCH_MAX_USES = parseInt(process.env.WEB_SEARCH_MAX_USES ?? '1', 10);
export const RESEARCH_SEARCHES = parseInt(process.env.RESEARCH_SEARCHES ?? '6', 10);
export const WEB_SEARCH_FAIL_RATE = parseFloat(process.env.WEB_SEARCH_FAIL_RATE ?? '0.4');

// Durable checkout demo. By default the first checkout's hotel step fails after
// the flight is reserved, making compensation visible in the UI history.
export const CHECKOUT_FAIL_HOTEL = ['1', 'true', 'yes', 'on'].includes(
  (process.env.CHECKOUT_FAIL_HOTEL ?? 'true').toLowerCase()
);
export const CHECKOUT_STEP_DELAY_MS = Math.max(
  0,
  Number(process.env.CHECKOUT_STEP_DELAY_SECONDS ?? '1.0') * 1000
);
// Demo pacing: artificial delay (seconds) each executeTool activity waits before
// returning, so instant DB lookups get a visible beat in the timeline (and a
// window to kill a worker mid-call). Set to 0 to disable. Mirrors python/config.py.
export const TOOL_DELAY_SECONDS = parseFloat(process.env.TOOL_DELAY_SECONDS ?? '1.0');

// ── Temporal connections — local dev server, Cloud (API key), or Cloud (mTLS). ──
// The Worker polls over a NativeConnection; the kill-switch bridge (control.ts)
// needs a client Connection to query its own workflow.
export async function workerConnection(): Promise<NativeConnection> {
  return NativeConnection.connect(CLIENT_CONFIG.connectionOptions);
}

export async function makeClient(): Promise<Client> {
  const connection = await Connection.connect(CLIENT_CONFIG.connectionOptions);
  return new Client({ connection, namespace: CLIENT_CONFIG.namespace });
}
