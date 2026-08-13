// Bridge so LLM activities can read their OWN conversation's kill-switch.
//
// The worker stashes its Temporal client here at startup; each LLM activity
// queries the workflow it's running under (`activityInfo().workflowId`) on every
// attempt — so the switch is scoped to that one conversation, not global.
// Resilient: any failure → 'not down', so the switch can never itself break the
// LLM. Ported from python/activities/control.py.

import { activityInfo } from '@temporalio/activity';
import type { Client } from '@temporalio/client';

let _client: Client | null = null;

export function setClient(client: Client): void {
  _client = client;
}

export async function llmDown(): Promise<boolean> {
  if (_client === null) return false;
  try {
    const wid = activityInfo().workflowExecution?.workflowId; // the conversation that called
    if (!wid) return false;
    return Boolean(await _client.workflow.getHandle(wid).query('is_llm_down'));
  } catch {
    return false;
  }
}
