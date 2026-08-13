// The research_destination pipeline's LLM steps, each a Temporal Activity.
// Ported from python/activities/research.py. Native Claude, no agent framework:
//   • structured steps (plan / write) force a JSON-schema response via
//     output_config.format and parse it.
//   • the search step hands Claude its built-in web_search server tool and
//     collects the summary it writes — the demo's LIVE data.
//
// Same retry philosophy + per-conversation kill-switch as llm.ts.

import Anthropic from '@anthropic-ai/sdk';
import { activityInfo } from '@temporalio/activity';
import { ApplicationFailure } from '@temporalio/common';

import * as config from '../config';
import * as prompts from '../prompts';
import * as control from './control';
import type { SearchItem, SearchPlan, WriteRequest, ReportData } from '../types';

// The web_search server tool. We use the BASIC variant (web_search_20250305) on
// purpose: the newer web_search_20260209 spins up a code-execution sandbox per
// search ("dynamic filtering"), which adds many seconds — too slow to watch in a
// live demo. Basic returns results directly and is much snappier.
const WEB_SEARCH_TOOL: Anthropic.WebSearchTool20250305 = {
  type: 'web_search_20250305',
  name: 'web_search',
  max_uses: config.WEB_SEARCH_MAX_USES,
};

const FATAL_STATUS = new Set([400, 401, 403, 404]);

type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';

function client(): Anthropic {
  return new Anthropic({ maxRetries: 0 });
}

function fatal(e: unknown): ApplicationFailure | null {
  if (e instanceof Anthropic.APIError && typeof e.status === 'number' && FATAL_STATUS.has(e.status)) {
    return ApplicationFailure.create({
      message: `LLM request rejected: ${e.message}`,
      type: 'LLMFatalError',
      nonRetryable: true,
    });
  }
  return null;
}

// Demo kill-switch: while flipped 'down', raise a RETRYABLE error → Temporal
// retries with backoff until it's flipped back.
async function guard(): Promise<void> {
  if (await control.llmDown()) {
    throw ApplicationFailure.create({
      message: 'LLM provider is unavailable (simulated outage).',
      type: 'LLMProviderDown',
    });
  }
}

// One structured-output call: Claude must answer with JSON matching `schema`.
async function structured(
  system: string,
  user: string,
  schema: Record<string, unknown>,
  maxTokens = 2048,
  effort: Effort = 'low'
): Promise<Record<string, unknown>> {
  let resp: Anthropic.Message;
  try {
    resp = await client().messages.create({
      model: config.ANTHROPIC_MODEL,
      max_tokens: maxTokens,
      system,
      messages: [{ role: 'user', content: user }],
      output_config: { effort, format: { type: 'json_schema', schema } },
    });
  } catch (e) {
    const f = fatal(e);
    if (f) throw f;
    throw e;
  }
  const text = resp.content
    .filter((b): b is Anthropic.TextBlock => b.type === 'text')
    .map((b) => b.text)
    .join('');
  return JSON.parse(text);
}

// ── plan ─────────────────────────────────────────────────────────────────────
export async function planSearches(brief: string): Promise<SearchPlan> {
  await guard();
  const system = prompts.planSystem(config.RESEARCH_SEARCHES);
  const data = await structured(system, `Research brief:\n${brief}`, prompts.PLAN_SCHEMA);
  const raw = (data.searches as SearchItem[] | undefined) ?? [];
  const searches = raw.map((s) => ({ query: s.query, reason: s.reason }));
  return { searches };
}

// ── search (native web_search tool) ──────────────────────────────────────────
// One durable search. If the worker dies mid-fan-out, only searches that hadn't
// completed re-run on restart — finished ones are already in the history.
export async function webSearch(item: SearchItem): Promise<string> {
  await guard();

  // Demo chaos: sometimes a search just flakes. Raise a RETRYABLE error so
  // Temporal retries this single activity (with backoff) while its siblings keep
  // going. Only the first attempt rolls the dice; retries always proceed.
  if (activityInfo().attempt === 1 && Math.random() < config.WEB_SEARCH_FAIL_RATE) {
    throw ApplicationFailure.create({
      message: `web_search transient failure (simulated) for ${JSON.stringify(item.query)}`,
      type: 'WebSearchFlaky',
    });
  }

  const user =
    `Search query: ${item.query}\n` +
    `Why this matters: ${item.reason}\n\n` +
    'Search the web and summarize the most relevant findings.';
  const messages: Anthropic.MessageParam[] = [{ role: 'user', content: user }];

  const c = client();
  let resp!: Anthropic.Message;
  try {
    // Server-side tool loop: Claude may pause (pause_turn) if it hits the
    // per-turn tool-use cap — re-send to let it resume, with a hard cap.
    for (let i = 0; i < 4; i++) {
      resp = await c.messages.create({
        model: config.ANTHROPIC_MODEL,
        max_tokens: 1024,
        system: prompts.SEARCH_SYSTEM,
        tools: [WEB_SEARCH_TOOL],
        output_config: { effort: 'low' },
        messages,
      });
      if (resp.stop_reason !== 'pause_turn') break;
      messages.push({ role: 'assistant', content: resp.content as unknown as Anthropic.ContentBlockParam[] });
    }
  } catch (e) {
    const f = fatal(e);
    if (f) throw f;
    throw e;
  }

  const summary = resp.content
    .filter((b): b is Anthropic.TextBlock => b.type === 'text')
    .map((b) => b.text)
    .join('')
    .trim();
  return summary ? `### ${item.query}\n${summary}` : `### ${item.query}\n(no findings)`;
}

// ── write ────────────────────────────────────────────────────────────────────
export async function writeReport(req: WriteRequest): Promise<ReportData> {
  await guard();
  const findings = req.findings.join('\n\n');
  const user = `Research brief:\n${req.brief}\n\nFindings from web searches:\n\n${findings}`;
  const data = await structured(prompts.WRITE_SYSTEM, user, prompts.WRITE_SCHEMA, 2500, 'low');
  return {
    short_summary: (data.short_summary as string) ?? '',
    markdown_report: (data.markdown_report as string) ?? '',
  };
}
