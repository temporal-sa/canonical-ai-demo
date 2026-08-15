"""TravelAgentWorkflow — a durable AI agent, written as a plain `while` loop.

This file IS the demo. An AI agent is just: ask the LLM what to do, run the
tool it asks for, feed the result back, repeat until it's done. Temporal makes
that loop *durable* — it survives crashes, retries failed steps for you, and
can pause to wait for a human.

The loop never hard-codes a tool name. Every tool call goes through `_dispatch`,
which runs it by its behavior:
  • plain    → run it, give the result back to the LLM   (most tools)
  • gated    → pause for approval, then run or delegate   (book_trip, create_invoice)
  • terminal → the tool's output IS the answer; stop      (research_destination)

To build a different agent: change the tools (prompts.py), the data
(activities/db.py), and the `_handlers` registry below. You don't touch the loop.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from activities.llm import call_llm
    from activities.research import (
        plan_searches,
        web_search,
        write_report,
    )
    from activities.tools import execute_tool
    from models.types import (
        ApprovalDecision,
        ChatMessage,
        CheckoutRequest,
        ItineraryItem,
        LLMRequest,
        LLMResponse,
        PendingConfirmation,
        ReportData,
        ResearchStatus,
        SearchItem,
        SearchPlan,
        ToolCall,
        ToolRequest,
        TurnResult,
        WriteRequest,
    )
    from prompts import system_prompt
    from workflows.checkout import CheckoutWorkflow

# Retry policies. Temporal retries a failed Activity for you — no try/except
# needed. maximum_attempts is unset, so it retries forever with backoff: a
# transient outage (rate limit, DB down) just waits and recovers on its own.
# The listed error types are permanent failures retrying can't fix, so they
# stop immediately instead.
LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    non_retryable_error_types=["LLMFatalError"],
)
TOOL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    non_retryable_error_types=["BookingDeclined"],
)


@dataclass
class ToolOutcome:
    """The result of running one tool. `terminal` means this IS the turn's
    answer — stop looping instead of sending it back to the LLM; `assistant_text`
    is what to show for it. Plain tools leave both at their defaults."""
    result: str
    terminal: bool = False
    assistant_text: str = ""


def _failure_message(e: ActivityError | ChildWorkflowError) -> str:
    return getattr(e.cause, "message", None) or "That action could not be completed."


@workflow.defn
class TravelAgentWorkflow:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []
        self.account_key: str = ""  # who we save data under (set in run)
        self.pending_confirmation: PendingConfirmation | None = None
        self.approval: ApprovalDecision | None = None
        self.turn_in_progress: bool = False
        self.llm_down: bool = False  # demo kill-switch, scoped to THIS conversation
        self.checkout_attempt: int = 0

        # The itinerary is just workflow state — a durable list, no DB table needed.
        self.itinerary: list[ItineraryItem] = []

        # research_destination — live fan-out progress for the UI
        self.phase: str = "idle"           # idle · planning · searching · writing
        self.plan: list[SearchItem] = []
        self.searches_total: int = 0
        self.searches_done: int = 0

        # The one place non-plain tools are wired in. Anything not listed here is
        # a plain tool. Each handler is `async (ToolCall) -> ToolOutcome`.
        self._handlers = {
            "research_destination": self._h_research,       # terminal
            "add_to_itinerary": self._h_add_to_itinerary,   # durable state
            "remove_from_itinerary": self._h_remove_from_itinerary,
            "book_trip": self._h_book_trip,                 # gated → checkout child workflow
            "create_invoice": self._h_create_invoice,       # gated
        }

    @workflow.run
    async def run(self, traveller_email: str) -> None:
        self.messages.append(ChatMessage(role="system", content=system_prompt(traveller_email)))

        # Each conversation is its own workflow with its own ID. We save data
        # (bookings) under that ID, so every chat is isolated and starts clean —
        # no reset needed between demos. The email is just for display.
        self.account_key = workflow.info().workflow_id

        while True:
            # 01 RECEIVE INPUT — wait for a chat message. The send_message update
            # drops it in and flips this flag to wake us up.
            await workflow.wait_condition(lambda: self.turn_in_progress)

            while True:
                # 02 PLAN — ask the LLM what to do next. It runs as an Activity, so
                # Temporal retries it if the provider is down (see _think).
                response = await self._think()
                self.messages.append(response.message)

                # No tool call means the LLM gave its final answer → turn is done.
                if not response.message.tool_calls:
                    break

                # 03 EXECUTE TOOLS — run each tool the LLM asked for. _dispatch
                # picks the behavior, so the loop stays generic. We hold any
                # terminal answer until every tool result is recorded.
                final_answer: str | None = None
                for call in response.message.tool_calls:
                    outcome = await self._dispatch(call)
                    self.messages.append(
                        ChatMessage(role="tool", content=outcome.result, tool_call_id=call.id)
                    )
                    if outcome.terminal:
                        final_answer = outcome.assistant_text

                # 04 PERSIST STATE — nothing to do here. self.messages and
                # self.itinerary are workflow state; Temporal saves them for you.

                # 05 LOOP / TERMINATE — a terminal tool's output is the answer, so
                # show it and stop. Otherwise loop back so the LLM can read the
                # tool results and decide the next step.
                if final_answer is not None:
                    self.messages.append(ChatMessage(role="assistant", content=final_answer))
                    break

            self.phase = "idle"
            self.turn_in_progress = False

    # ── the loop's two helpers ───────────────────────────────────────────────────
    async def _think(self) -> LLMResponse:
        """02 PLAN: call the LLM as an Activity so Temporal retries transient
        failures. If it fails for good, return a plain apology (no tool call) so
        the loop ends the turn gracefully and the chat stays alive."""
        try:
            return await workflow.execute_activity(
                call_llm,
                LLMRequest(messages=self.messages),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=LLM_RETRY,
            )
        except ActivityError:
            return LLMResponse(message=ChatMessage(
                role="assistant",
                content="I'm sorry — I hit an error I couldn't recover from. "
                        "Please try again in a moment.",
            ))

    async def _dispatch(self, call: ToolCall) -> ToolOutcome:
        """Run one tool by its behavior. Default: run it as an Activity and hand
        the result back to the LLM. Tools in _handlers do something special.

        If an Activity fails permanently (e.g. a rejected booking), give the
        error back to the LLM so it can explain — the chat continues."""
        handler = self._handlers.get(call.name, self._run_plain_tool)
        try:
            return await handler(call)
        except (ActivityError, ChildWorkflowError) as e:
            return ToolOutcome(result=json.dumps({"error": _failure_message(e)}))

    async def _run_plain_tool(self, call: ToolCall) -> ToolOutcome:
        """The default behavior: just run the tool as an Activity."""
        result = await workflow.execute_activity(
            execute_tool,
            ToolRequest(call=call, account_key=self.account_key),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TOOL_RETRY,
            summary=call.name,
        )
        return ToolOutcome(result=result)

    # ── how the UI talks to a running workflow: update, signals, queries ─────────
    @workflow.update
    async def send_message(self, text: str) -> TurnResult:
        """One chat turn. An *update* sends input in and gets a result back: add
        the message, wake the loop, and wait until the turn finishes — either a
        reply, or paused for a human approval."""
        turn_start = len(self.messages)
        self.messages.append(ChatMessage(role="user", content=text))
        self.turn_in_progress = True
        await workflow.wait_condition(
            lambda: not self.turn_in_progress
            or self.pending_confirmation is not None
        )
        reply = self._last_assistant_text(since=turn_start)  # only THIS turn's text
        if self.pending_confirmation is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)

    # A *signal* sends input in without waiting for a result (fire-and-forget).
    @workflow.signal
    def confirm_action(self, decision: ApprovalDecision) -> None:
        """The human approved or rejected the paused action (a booking/invoice)."""
        self.approval = decision

    @workflow.signal
    def set_llm_status(self, down: bool) -> None:
        self.llm_down = down

    # A *query* reads workflow state without changing it.
    @workflow.query
    def is_llm_down(self) -> bool:
        return self.llm_down

    @workflow.query
    def transcript(self) -> list[ChatMessage]:
        """What the chat window shows: just the user/assistant text messages."""
        return [m for m in self.messages
                if m.role in ("user", "assistant") and m.content]

    @workflow.query
    def pending_approval(self) -> PendingConfirmation | None:
        return self.pending_confirmation

    @workflow.query
    def research_status(self) -> ResearchStatus:
        """What the UI polls to show research progress live: the phase, the search
        plan, and how many searches are done."""
        return ResearchStatus(
            phase=self.phase,
            plan=self.plan,
            searches_total=self.searches_total,
            searches_done=self.searches_done,
        )

    @workflow.query
    def itinerary_view(self) -> list[ItineraryItem]:
        return self.itinerary

    # ── the tool behaviors (the domain). The loop dispatches into these. ─────────

    # TERMINAL: the cited guide IS the answer, so we don't loop back to the LLM
    # (that would just repeat it). It still goes into history so follow-ups stay
    # grounded ("add the nonstop flight").
    async def _h_research(self, call: ToolCall) -> ToolOutcome:
        report = await self._research(call.args.get("query", ""))
        return ToolOutcome(
            result=f"{report.short_summary}\n\n{report.markdown_report}",
            terminal=True,
            assistant_text=report.markdown_report,
        )

    async def _research(self, query: str) -> ReportData:
        """plan → run the searches in parallel → write the guide."""
        self.plan = []
        self.searches_total = 0
        self.searches_done = 0

        self.phase = "planning"
        plan: SearchPlan = await workflow.execute_activity(
            plan_searches, query,
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=LLM_RETRY,
        )
        self.plan = plan.searches
        self.searches_total = len(self.plan)

        # Run all searches at once as parallel Activities. Kill the worker
        # mid-search and only the unfinished ones re-run — finished ones are
        # remembered. (A plain Python loop would redo them all.)
        self.phase = "searching"

        async def _run_search(item: SearchItem) -> str:
            result = await workflow.execute_activity(
                web_search, item,
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=LLM_RETRY,
            )
            self.searches_done += 1
            return result

        findings = await asyncio.gather(*[_run_search(s) for s in self.plan])

        self.phase = "writing"
        report: ReportData = await workflow.execute_activity(
            write_report, WriteRequest(brief=query, findings=list(findings)),
            start_to_close_timeout=timedelta(seconds=180),
            retry_policy=LLM_RETRY,
        )
        self.phase = "idle"
        return report

    # The Activity looks up the catalog row; the itinerary itself is workflow
    # state (durable, no DB table needed).
    async def _h_add_to_itinerary(self, call: ToolCall) -> ToolOutcome:
        result = await workflow.execute_activity(
            execute_tool, ToolRequest(call=call, account_key=self.account_key),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TOOL_RETRY, summary=call.name,
        )
        rows = json.loads(result)
        if isinstance(rows, dict) and rows.get("error"):
            return ToolOutcome(result=result)
        existing = {i.item_id for i in self.itinerary}
        added: list[ItineraryItem] = []
        for r in rows:
            item = ItineraryItem(
                kind=r["kind"], ref_id=r["ref_id"], title=r.get("title", ""),
                subtitle=r.get("subtitle", ""), price=float(r.get("price") or 0),
            )
            if item.item_id in existing:
                continue
            self.itinerary.append(item)
            existing.add(item.item_id)
            added.append(item)
        return ToolOutcome(result=json.dumps({
            "added": [{"item_id": a.item_id, "title": a.title} for a in added],
            "itinerary_size": len(self.itinerary),
            "itinerary_total": round(sum(i.price for i in self.itinerary), 2),
        }))

    async def _h_remove_from_itinerary(self, call: ToolCall) -> ToolOutcome:
        ids = set(call.args.get("item_ids", []) or [])
        before = len(self.itinerary)
        self.itinerary = [i for i in self.itinerary if i.item_id not in ids]
        return ToolOutcome(result=json.dumps({
            "removed": before - len(self.itinerary),
            "itinerary_size": len(self.itinerary),
            "itinerary_total": round(sum(i.price for i in self.itinerary), 2),
        }))

    # GATED write actions: pause for the human to approve, then do the work.
    async def _await_confirmation(self) -> ApprovalDecision:
        """Pause until the human decides. wait_condition is a *durable* pause — it
        survives a worker restart and costs nothing while waiting."""
        await workflow.wait_condition(lambda: self.approval is not None)
        decision, self.approval, self.pending_confirmation = self.approval, None, None
        return decision

    async def _h_book_trip(self, call: ToolCall) -> ToolOutcome:
        """Book the whole itinerary — pause for approval, then settle."""
        if not self.itinerary:
            return ToolOutcome(result=json.dumps({
                "error": "The itinerary is empty — add flights, hotels, "
                         "or activities before booking."}))
        items = [{"kind": i.kind, "ref_id": i.ref_id, "title": i.title, "price": i.price}
                 for i in self.itinerary]
        total = round(sum(i.price for i in self.itinerary), 2)
        summary = f"{len(items)} item(s) — ${total:,.2f}"

        # Setting this parks the turn; the UI shows a Confirm button.
        self.pending_confirmation = PendingConfirmation(
            action="book_trip", title="Booking approval required",
            detail=summary, amount=total,
            args={"items": [{"title": i.title, "price": i.price} for i in self.itinerary]},
        )
        decision = await self._await_confirmation()
        if not decision.approved:
            reason = f" Reason: {decision.reason}" if decision.reason else ""
            return ToolOutcome(result=f"The traveller DECLINED this booking.{reason}")

        self.checkout_attempt += 1
        checkout_id = f"{self.account_key}-checkout-{self.checkout_attempt}"
        checkout = await workflow.execute_child_workflow(
            CheckoutWorkflow.run,
            CheckoutRequest(
                account_key=self.account_key,
                items=list(self.itinerary),
                summary=summary,
            ),
            id=checkout_id,
            static_summary="Agent-invoked durable checkout",
            static_details=(
                "Books itinerary items in order and compensates completed "
                "reservations if a later step fails."
            ),
        )
        if checkout.status == "booked":
            self.itinerary = []
        return ToolOutcome(result=checkout.model_dump_json())

    async def _h_create_invoice(self, call: ToolCall) -> ToolOutcome:
        """Invoice one chosen flight — pause for approval, then settle."""
        amount = round(float(call.args.get("amount") or 0), 2)
        flight_details = call.args.get("flight_details", "")
        if amount <= 0 or not flight_details:
            return ToolOutcome(result=json.dumps({
                "error": "Need a positive amount and a flight description "
                         "to create an invoice."}))
        self.pending_confirmation = PendingConfirmation(
            action="create_invoice", title="Create invoice",
            detail=flight_details, amount=amount,
            args={"amount": amount, "flight_details": flight_details},
        )
        decision = await self._await_confirmation()
        if not decision.approved:
            reason = f" Reason: {decision.reason}" if decision.reason else ""
            return ToolOutcome(result=f"The traveller DECLINED the invoice.{reason}")

        invoice_call = ToolCall(id="invoice", name="create_invoice",
                                args={"amount": amount, "flight_details": flight_details})
        result = await workflow.execute_activity(
            execute_tool, ToolRequest(call=invoice_call, account_key=self.account_key),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TOOL_RETRY, summary=invoice_call.name,
        )
        return ToolOutcome(result=result)

    def _last_assistant_text(self, since: int = 0) -> str:
        for m in reversed(self.messages[since:]):
            if m.role == "assistant" and m.content:
                return m.content
        return ""
