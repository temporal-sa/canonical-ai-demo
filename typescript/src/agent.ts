// TravelAgentWorkflow — a durable AI agent, written as a plain loop.
// TypeScript port of python/workflows/agent.py. This file IS the demo.
//
// An AI agent is just: ask the LLM what to do, run the tool it asks for, feed
// the result back, repeat until it's done. Temporal makes that loop *durable* —
// it survives crashes, retries failed steps, and can pause to wait for a human.
//
// The loop never hard-codes a tool name. Every tool call goes through dispatch(),
// which runs it by its behavior:
//   • plain    → run it, give the result back to the LLM   (most tools)
//   • gated    → pause for approval, then run or delegate   (book_trip, create_invoice)
//   • terminal → the tool's output IS the answer; stop      (research_destination)
//
// This file is bundled into the Temporal V8 sandbox: it must stay deterministic
// — no I/O, no Node APIs, no Date.now()/Math.random(). All I/O is in activities.

import {
  defineUpdate,
  defineSignal,
  defineQuery,
  setHandler,
  condition,
  proxyActivities,
  workflowInfo,
  ActivityFailure,
  ApplicationFailure,
  ChildWorkflowFailure,
  executeChild,
} from '@temporalio/workflow';
import type { RetryPolicy } from '@temporalio/common';
import type * as activities from './activities';
import { systemPrompt } from './prompts';
import type {
  ApprovalDecision,
  ChatMessage,
  CheckoutRequest,
  ItineraryItem,
  LLMResponse,
  PendingConfirmation,
  ReportData,
  ResearchStatus,
  SearchItem,
  SearchPlan,
  ToolCall,
  TurnResult,
} from './types';
import { CheckoutWorkflow } from './checkout';

export { CheckoutWorkflow } from './checkout';

// Retry policies. Temporal retries a failed Activity for you — no try/catch
// needed. maximumAttempts is unset, so it retries forever with backoff: a
// transient outage (rate limit, DB down) just waits and recovers. The listed
// error types are permanent failures retrying can't fix, so they stop at once.
const LLM_RETRY: RetryPolicy = {
  initialInterval: '1 second',
  backoffCoefficient: 2,
  maximumInterval: '10 seconds',
  nonRetryableErrorTypes: ['LLMFatalError'],
};
const TOOL_RETRY: RetryPolicy = {
  initialInterval: '1 second',
  backoffCoefficient: 2,
  maximumInterval: '10 seconds',
  nonRetryableErrorTypes: ['BookingDeclined'],
};

// One proxy per activity — each carries its own timeout + retry policy.
const { callLlm } = proxyActivities<typeof activities>({ startToCloseTimeout: '60 seconds', retry: LLM_RETRY });
const { planSearches } = proxyActivities<typeof activities>({ startToCloseTimeout: '90 seconds', retry: LLM_RETRY });
const { webSearch } = proxyActivities<typeof activities>({ startToCloseTimeout: '120 seconds', retry: LLM_RETRY });
const { writeReport } = proxyActivities<typeof activities>({ startToCloseTimeout: '180 seconds', retry: LLM_RETRY });
// execute_tool carries a per-call `summary` (the tool name), so it's built via
// runTool() below rather than a single fixed proxy — see the research pipeline
// activities, which are deliberately left unsummarized.

// ── the contract's string names — MUST match the gateway / other SDKs ──
export const sendMessage = defineUpdate<TurnResult, [string]>('send_message');
export const confirmAction = defineSignal<[ApprovalDecision]>('confirm_action');
export const setLlmStatus = defineSignal<[boolean]>('set_llm_status');
export const isLlmDown = defineQuery<boolean>('is_llm_down');
export const transcript = defineQuery<ChatMessage[]>('transcript');
export const pendingApproval = defineQuery<PendingConfirmation | null>('pending_approval');
export const researchStatus = defineQuery<ResearchStatus>('research_status');
export const itineraryView = defineQuery<ItineraryItem[]>('itinerary_view');

// The result of running one tool. `terminal` means this IS the turn's answer —
// stop looping instead of sending it back to the LLM; `assistantText` is what to
// show for it. Plain tools leave both at their defaults.
interface ToolOutcome {
  result: string;
  terminal?: boolean;
  assistantText?: string;
}

export async function TravelAgentWorkflow(travellerEmail: string): Promise<void> {
  // ── workflow state (durable; Temporal saves it for you — no DB table) ──
  const messages: ChatMessage[] = [];
  let accountKey = ''; // who we save data under (set below)
  let pendingConfirmation: PendingConfirmation | null = null;
  let approval: ApprovalDecision | null = null;
  let turnInProgress = false;
  let llmDown = false; // demo kill-switch, scoped to THIS conversation
  let checkoutAttempt = 0;
  let itinerary: ItineraryItem[] = [];

  // research_destination — live fan-out progress for the UI
  let phase = 'idle'; // idle · planning · searching · writing
  let plan: SearchItem[] = [];
  let searchesTotal = 0;
  let searchesDone = 0;

  const itemId = (i: { kind: string; ref_id: number }) => `${i.kind}-${i.ref_id}`;
  const round2 = (n: number) => Math.round(n * 100) / 100;
  const itinTotal = () => round2(itinerary.reduce((s, i) => s + i.price, 0));
  // format like Python's `${x:,.2f}` — thousands separators + 2 decimals.
  const money = (n: number) => n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

  function lastAssistantText(since = 0): string {
    for (let i = messages.length - 1; i >= since; i--) {
      const m = messages[i];
      if (m.role === 'assistant' && m.content) return m.content;
    }
    return '';
  }

  function failureMessage(e: ActivityFailure | ChildWorkflowFailure): string {
    const cause = e.cause;
    if (cause instanceof ApplicationFailure && cause.message) return cause.message;
    return 'That action could not be completed.';
  }

  // ── the loop's two helpers ──────────────────────────────────────────────────
  // PLAN: call the LLM as an Activity so Temporal retries transient failures. If
  // it fails for good, return a plain apology (no tool call) so the turn ends
  // gracefully and the chat stays alive.
  async function think(): Promise<LLMResponse> {
    try {
      return await callLlm({ messages });
    } catch (e) {
      if (e instanceof ActivityFailure) {
        return {
          message: {
            role: 'assistant',
            content:
              "I'm sorry — I hit an error I couldn't recover from. Please try again in a moment.",
          },
        };
      }
      throw e;
    }
  }

  // The one place non-plain tools are wired in. Anything not listed here is a
  // plain tool. Each handler is (ToolCall) => Promise<ToolOutcome>.
  const handlers: Record<string, (call: ToolCall) => Promise<ToolOutcome>> = {
    research_destination: hResearch, // terminal
    add_to_itinerary: hAddToItinerary, // durable state
    remove_from_itinerary: hRemoveFromItinerary,
    book_trip: hBookTrip, // gated → checkout child workflow
    create_invoice: hCreateInvoice, // gated
  };

  // Run one tool by its behavior. Default: run it as an Activity and hand the
  // result back to the LLM; tools in `handlers` do something special. If an
  // Activity fails permanently (e.g. a rejected booking), give the error back
  // to the LLM so it can explain — the chat continues.
  async function dispatch(call: ToolCall): Promise<ToolOutcome> {
    const handler = handlers[call.name] ?? runPlainTool;
    try {
      return await handler(call);
    } catch (e) {
      if (e instanceof ActivityFailure || e instanceof ChildWorkflowFailure) {
        return { result: JSON.stringify({ error: failureMessage(e) }) };
      }
      throw e;
    }
  }

  // Run execute_tool. The tool name (call.name) shows as the activity's summary
  // on the Temporal timeline. Building the proxy per call is cheap.
  function runTool(call: ToolCall) {
    const { executeTool } = proxyActivities<typeof activities>({
      startToCloseTimeout: '30 seconds',
      retry: TOOL_RETRY,
      summary: call.name,
    });
    return executeTool({ call, account_key: accountKey });
  }

  async function runPlainTool(call: ToolCall): Promise<ToolOutcome> {
    const result = await runTool(call);
    return { result };
  }

  // ── the tool behaviors (the domain). dispatch() runs these. ─────────────────

  // TERMINAL: the cited guide IS the answer, so we don't loop back to the LLM
  // (that would just repeat it). It still goes into history so follow-ups stay
  // grounded ("add the nonstop flight").
  async function hResearch(call: ToolCall): Promise<ToolOutcome> {
    const report = await research((call.args.query as string) ?? '');
    return {
      result: `${report.short_summary}\n\n${report.markdown_report}`,
      terminal: true,
      assistantText: report.markdown_report,
    };
  }

  // plan → run the searches in parallel → write the guide.
  async function research(query: string): Promise<ReportData> {
    plan = [];
    searchesTotal = 0;
    searchesDone = 0;

    phase = 'planning';
    const p: SearchPlan = await planSearches(query);
    plan = p.searches;
    searchesTotal = plan.length;

    // Run all searches at once as parallel Activities. Kill the worker
    // mid-search and only the unfinished ones re-run — finished ones are
    // remembered. (A plain loop would redo them all.)
    phase = 'searching';
    const findings = await Promise.all(
      plan.map(async (item) => {
        const result = await webSearch(item);
        searchesDone += 1;
        return result;
      })
    );

    phase = 'writing';
    const report = await writeReport({ brief: query, findings });
    phase = 'idle';
    return report;
  }

  // The Activity looks up the catalog row; the itinerary itself is workflow
  // state (durable, no DB table needed).
  async function hAddToItinerary(call: ToolCall): Promise<ToolOutcome> {
    const result = await runTool(call);
    const rows = JSON.parse(result);
    if (rows && !Array.isArray(rows) && rows.error) return { result };
    const existing = new Set(itinerary.map(itemId));
    const added: ItineraryItem[] = [];
    for (const r of rows as Record<string, unknown>[]) {
      const item: ItineraryItem = {
        kind: r.kind as ItineraryItem['kind'],
        ref_id: r.ref_id as number,
        title: (r.title as string) ?? '',
        subtitle: (r.subtitle as string) ?? '',
        price: Number(r.price ?? 0),
      };
      const id = itemId(item);
      if (existing.has(id)) continue;
      itinerary.push(item);
      existing.add(id);
      added.push(item);
    }
    return {
      result: JSON.stringify({
        added: added.map((a) => ({ item_id: itemId(a), title: a.title })),
        itinerary_size: itinerary.length,
        itinerary_total: itinTotal(),
      }),
    };
  }

  async function hRemoveFromItinerary(call: ToolCall): Promise<ToolOutcome> {
    const ids = new Set((call.args.item_ids as string[]) ?? []);
    const before = itinerary.length;
    itinerary = itinerary.filter((i) => !ids.has(itemId(i)));
    return {
      result: JSON.stringify({
        removed: before - itinerary.length,
        itinerary_size: itinerary.length,
        itinerary_total: itinTotal(),
      }),
    };
  }

  // GATED write actions: pause for the human to approve, then do the work.
  // wait via condition() is a *durable* pause — it survives a worker restart and
  // costs nothing while waiting.
  async function awaitConfirmation(): Promise<ApprovalDecision> {
    await condition(() => approval !== null);
    const decision = approval!;
    approval = null;
    pendingConfirmation = null;
    return decision;
  }

  async function hBookTrip(call: ToolCall): Promise<ToolOutcome> {
    if (!itinerary.length) {
      return {
        result: JSON.stringify({
          error: 'The itinerary is empty — add flights, hotels, or activities before booking.',
        }),
      };
    }
    const items = itinerary.map((i) => ({ kind: i.kind, ref_id: i.ref_id, title: i.title, price: i.price }));
    const total = itinTotal();
    const summary = `${items.length} item(s) — $${money(total)}`;

    // Setting this parks the turn; the UI shows a Confirm button.
    pendingConfirmation = {
      action: 'book_trip',
      title: 'Booking approval required',
      detail: summary,
      amount: total,
      args: { items: itinerary.map((i) => ({ title: i.title, price: i.price })) },
    };
    const decision = await awaitConfirmation();
    if (!decision.approved) {
      const reason = decision.reason ? ` Reason: ${decision.reason}` : '';
      return { result: `The traveller DECLINED this booking.${reason}` };
    }

    checkoutAttempt += 1;
    const checkoutRequest: CheckoutRequest = {
      account_key: accountKey,
      items: [...itinerary],
      summary,
    };
    const checkout = await executeChild(CheckoutWorkflow, {
      args: [checkoutRequest],
      workflowId: `${accountKey}-checkout-${checkoutAttempt}`,
    });
    if (checkout.status === 'booked') itinerary = [];
    return { result: JSON.stringify(checkout) };
  }

  async function hCreateInvoice(call: ToolCall): Promise<ToolOutcome> {
    const amount = round2(Number(call.args.amount ?? 0));
    const flightDetails = (call.args.flight_details as string) ?? '';
    if (amount <= 0 || !flightDetails) {
      return {
        result: JSON.stringify({
          error: 'Need a positive amount and a flight description to create an invoice.',
        }),
      };
    }
    pendingConfirmation = {
      action: 'create_invoice',
      title: 'Create invoice',
      detail: flightDetails,
      amount,
      args: { amount, flight_details: flightDetails },
    };
    const decision = await awaitConfirmation();
    if (!decision.approved) {
      const reason = decision.reason ? ` Reason: ${decision.reason}` : '';
      return { result: `The traveller DECLINED the invoice.${reason}` };
    }

    const invoiceCall: ToolCall = {
      id: 'invoice',
      name: 'create_invoice',
      args: { amount, flight_details: flightDetails },
    };
    const result = await runTool(invoiceCall);
    return { result };
  }

  // ── how the UI talks to a running workflow: update, signals, queries ────────
  // An *update* sends input in and gets a result back: add the message, wake the
  // loop, and wait until the turn finishes — either a reply, or paused for a
  // human approval.
  setHandler(sendMessage, async (text): Promise<TurnResult> => {
    const turnStart = messages.length;
    messages.push({ role: 'user', content: text });
    turnInProgress = true;
    await condition(() => !turnInProgress || pendingConfirmation !== null);
    const reply = lastAssistantText(turnStart); // only THIS turn's text
    return pendingConfirmation !== null
      ? { status: 'awaiting_approval', reply }
      : { status: 'reply', reply };
  });

  // *signals* send input without waiting for a result (fire-and-forget).
  setHandler(confirmAction, (decision) => {
    approval = decision;
  });
  setHandler(setLlmStatus, (down) => {
    llmDown = down;
  });

  // *queries* read workflow state without changing it.
  setHandler(isLlmDown, () => llmDown);
  setHandler(transcript, () =>
    messages.filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content)
  );
  setHandler(pendingApproval, () => pendingConfirmation);
  setHandler(researchStatus, (): ResearchStatus => ({
    phase,
    plan,
    searches_total: searchesTotal,
    searches_done: searchesDone,
  }));
  setHandler(itineraryView, () => itinerary);

  // ── the durable ReAct loop ──────────────────────────────────────────────────
  messages.push({ role: 'system', content: systemPrompt(travellerEmail) });
  // Each conversation is its own workflow with its own ID. We save data
  // (bookings) under that ID, so every chat is isolated and starts clean.
  accountKey = workflowInfo().workflowId;

  while (true) {
    // 01 RECEIVE INPUT — wait for a chat message. send_message flips this flag.
    await condition(() => turnInProgress);

    while (true) {
      // 02 PLAN — ask the LLM what to do next (retryable Activity).
      const response = await think();
      messages.push(response.message);

      // No tool call means the LLM gave its final answer → turn is done.
      const calls = response.message.tool_calls ?? [];
      if (calls.length === 0) break;

      // 03 EXECUTE TOOLS — run each tool the LLM asked for. dispatch() picks the
      // behavior. Hold any terminal answer until every tool result is recorded.
      let finalAnswer: string | null = null;
      for (const call of calls) {
        const outcome = await dispatch(call);
        messages.push({ role: 'tool', content: outcome.result, tool_call_id: call.id });
        if (outcome.terminal) finalAnswer = outcome.assistantText ?? '';
      }

      // 04 PERSIST STATE — nothing to do; messages + itinerary are workflow state.
      // 05 LOOP / TERMINATE — a terminal tool's output is the answer; show it and
      // stop. Otherwise loop so the LLM can read the tool results and continue.
      if (finalAnswer !== null) {
        messages.push({ role: 'assistant', content: finalAnswer });
        break;
      }
    }

    phase = 'idle';
    turnInProgress = false;
  }
}
