// The ONE place that reads environment config for the TS worker — mirrors
// python/config.py so both SDKs share the same .env (and the same task queue).

import * as path from 'path';
import * as dotenv from 'dotenv';
import { NativeConnection } from '@temporalio/worker';
import { Client, Connection } from '@temporalio/client';

// repo-root .env first (shared demoer quick-switch), then a local override.
dotenv.config({ path: path.resolve(__dirname, '..', '..', '.env') });
dotenv.config();

// TEMPORAL_TASK_QUEUE is what the demo-cloud registry's crashable-workspace
// feature injects (<base>-<workspace-id>); fall back to legacy TASK_QUEUE, then
// the shared default. Mirrors python/config.py.
export const TASK_QUEUE = process.env.TEMPORAL_TASK_QUEUE ?? process.env.TASK_QUEUE ?? 'travel-agent';
export const TEMPORAL_ADDRESS = process.env.TEMPORAL_ADDRESS ?? 'localhost:7233';
export const TEMPORAL_NAMESPACE = process.env.TEMPORAL_NAMESPACE ?? 'default';

const TEMPORAL_API_KEY = process.env.TEMPORAL_API_KEY;
const TEMPORAL_TLS_CERT = process.env.TEMPORAL_TLS_CERT;
const TEMPORAL_TLS_KEY = process.env.TEMPORAL_TLS_KEY;

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
export const WEB_SEARCH_FAIL_RATE = parseFloat(process.env.WEB_SEARCH_FAIL_RATE ?? '0.3');

// Durable checkout demo. By default the hotel step fails after the flight is
// reserved, making CheckoutWorkflow's compensation visible in the UI history.
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
  if (TEMPORAL_API_KEY) {
    return NativeConnection.connect({ address: TEMPORAL_ADDRESS, apiKey: TEMPORAL_API_KEY, tls: true });
  }
  if (TEMPORAL_TLS_CERT && TEMPORAL_TLS_KEY) {
    const fs = await import('fs');
    return NativeConnection.connect({
      address: TEMPORAL_ADDRESS,
      tls: {
        clientCertPair: {
          crt: fs.readFileSync(TEMPORAL_TLS_CERT),
          key: fs.readFileSync(TEMPORAL_TLS_KEY),
        },
      },
    });
  }
  return NativeConnection.connect({ address: TEMPORAL_ADDRESS });
}

export async function makeClient(): Promise<Client> {
  let connection: Connection;
  if (TEMPORAL_API_KEY) {
    connection = await Connection.connect({ address: TEMPORAL_ADDRESS, apiKey: TEMPORAL_API_KEY, tls: true });
  } else if (TEMPORAL_TLS_CERT && TEMPORAL_TLS_KEY) {
    const fs = await import('fs');
    connection = await Connection.connect({
      address: TEMPORAL_ADDRESS,
      tls: {
        clientCertPair: {
          crt: fs.readFileSync(TEMPORAL_TLS_CERT),
          key: fs.readFileSync(TEMPORAL_TLS_KEY),
        },
      },
    });
  } else {
    connection = await Connection.connect({ address: TEMPORAL_ADDRESS });
  }
  return new Client({ connection, namespace: TEMPORAL_NAMESPACE });
}
