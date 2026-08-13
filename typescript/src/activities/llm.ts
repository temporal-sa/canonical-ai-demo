// The PLAN step: call the LLM as a Temporal Activity. Anthropic-only (the TS
// worker doesn't carry the OpenAI path). Ported from python/activities/llm.py.
//
// Retry philosophy: the SDK's own retries are OFF (maxRetries: 0) so Temporal
// owns ALL retries — every rate-limit or outage is visible as a retry in
// workflow history. Requests the provider rejects outright (bad auth/request)
// are marked non-retryable: retrying can't fix those.

import Anthropic from '@anthropic-ai/sdk';
import { ApplicationFailure } from '@temporalio/common';

import * as config from '../config';
import * as control from './control';
import { TOOLS } from '../prompts';
import type { LLMRequest, LLMResponse, ToolCall } from '../types';

// HTTP statuses the provider rejects outright — retrying can't fix these.
const FATAL_STATUS = new Set([400, 401, 403, 404]);

export async function callLlm(req: LLMRequest): Promise<LLMResponse> {
  // Demo kill-switch (the UI "API status" panel). While flipped to 'down', raise
  // a RETRYABLE error → Temporal retries with backoff until it's flipped back,
  // and the retries show in the history.
  if (await control.llmDown()) {
    throw ApplicationFailure.create({
      message: 'LLM provider is unavailable (simulated outage).',
      type: 'LLMProviderDown',
    });
  }
  return callAnthropic(req);
}

async function callAnthropic(req: LLMRequest): Promise<LLMResponse> {
  const client = new Anthropic({ maxRetries: 0 });

  const system = req.messages.find((m) => m.role === 'system')?.content ?? '';
  const messages: Anthropic.MessageParam[] = [];
  for (const m of req.messages) {
    if (m.role === 'system') continue;
    if (m.role === 'user') {
      messages.push({ role: 'user', content: m.content });
    } else if (m.role === 'assistant') {
      const blocks: Anthropic.ContentBlockParam[] = [];
      if (m.content) blocks.push({ type: 'text', text: m.content });
      for (const c of m.tool_calls ?? []) {
        blocks.push({ type: 'tool_use', id: c.id, name: c.name, input: c.args });
      }
      messages.push({ role: 'assistant', content: blocks });
    } else {
      // role === 'tool' → an Anthropic tool_result, batched into the trailing
      // user turn if the previous message already ended with one.
      const block: Anthropic.ToolResultBlockParam = {
        type: 'tool_result',
        tool_use_id: m.tool_call_id!,
        content: m.content,
      };
      const last = messages[messages.length - 1];
      if (
        last &&
        last.role === 'user' &&
        Array.isArray(last.content) &&
        last.content.length &&
        (last.content[last.content.length - 1] as Anthropic.ContentBlockParam).type === 'tool_result'
      ) {
        (last.content as Anthropic.ContentBlockParam[]).push(block);
      } else {
        messages.push({ role: 'user', content: [block] });
      }
    }
  }

  let resp: Anthropic.Message;
  try {
    resp = await client.messages.create({
      model: config.ANTHROPIC_MODEL,
      max_tokens: 2048,
      system,
      tools: TOOLS as unknown as Anthropic.Tool[],
      messages,
    });
  } catch (e) {
    if (e instanceof Anthropic.APIError && typeof e.status === 'number' && FATAL_STATUS.has(e.status)) {
      throw ApplicationFailure.create({
        message: `LLM request rejected: ${e.message}`,
        type: 'LLMFatalError',
        nonRetryable: true,
      });
    }
    throw e;
  }

  let text = '';
  const calls: ToolCall[] = [];
  for (const b of resp.content) {
    if (b.type === 'text') text += b.text;
    else if (b.type === 'tool_use') {
      calls.push({ id: b.id, name: b.name, args: (b.input ?? {}) as Record<string, unknown> });
    }
  }
  return { message: { role: 'assistant', content: text, tool_calls: calls } };
}
