"""TravelAgentWorkflow — the durable agentic ReAct loop.

This file IS the demo. The numbered comments are slide 28's five primitives:
  01 Receive Input · 02 Plan · 03 Execute Tools · 04 Persist State · 05 Loop/Terminate

The agentic loop is just a `while` loop — Temporal makes it durable,
retryable, and pausable-for-humans.
"""

import asyncio
import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from activities.llm import call_llm
    from activities.research import (
        enrich_query,
        plan_clarifications,
        plan_searches,
        web_search,
        write_report,
    )
    from activities.tools import execute_tool
    from models.types import (
        ApprovalDecision,
        ChatMessage,
        ClarifyResult,
        EnrichRequest,
        ItineraryItem,
        LLMRequest,
        PendingClarification,
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

# Explicit retry policies (slide 31). maximum_attempts is unset = retry forever
# with backoff — so a transient outage (rate-limit, DB down, flaky gateway) just
# waits and recovers. The non_retryable types are the failures retrying can't
# fix: a rejected LLM request, a business decline. Those fail immediately.
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


def _failure_message(e: ActivityError) -> str:
    return getattr(e.cause, "message", None) or "That action could not be completed."


@workflow.defn
class TravelAgentWorkflow:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []
        self.pending_confirmation: PendingConfirmation | None = None
        self.approval: ApprovalDecision | None = None
        self.turn_in_progress: bool = False
        self.llm_down: bool = False  # demo kill-switch, scoped to THIS conversation

        # itinerary — durable, conversation-scoped workflow state (no DB table needed)
        self.itinerary: list[ItineraryItem] = []

        # research_destination — clarification pause + live fan-out progress for the UI
        self.pending_clarifications: PendingClarification | None = None
        self.clar_answers: dict[str, str] = {}
        self.answers_submitted: bool = False
        self.clarified_once: bool = False  # only clarify on the first research pass
        self.phase: str = "idle"           # idle · clarifying · planning · searching · writing
        self.plan: list[SearchItem] = []
        self.searches_total: int = 0
        self.searches_done: int = 0

    @workflow.run
    async def run(self, traveller_email: str) -> None:
        self.messages.append(ChatMessage(role="system", content=system_prompt(traveller_email)))

        # DB identity is the workflow ID, NOT the traveller email. Everything the
        # agent persists (bookings) is scoped to THIS conversation: a new
        # conversation is a new workflow ID = a clean slate. So there is no
        # cross-session memory, and back-to-back demos never see each other's data —
        # no reset or reseed needed. traveller_email stays the real, authenticated
        # email, used only for the system-prompt display above.
        account_key = workflow.info().workflow_id

        while True:
            await workflow.wait_condition(lambda: self.turn_in_progress)

            while True:
                try:
                    plan_response = await workflow.execute_activity(
                        call_llm,
                        LLMRequest(messages=self.messages),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=LLM_RETRY,
                    )
                except ActivityError:
                    # Unrecoverable LLM failure (rejected request, or gave up).
                    # Surface it and end the turn — the conversation stays alive.
                    self.messages.append(ChatMessage(
                        role="assistant",
                        content="I'm sorry — I hit an error I couldn't recover from. "
                                "Please try again in a moment.",
                    ))
                    break
                self.messages.append(plan_response.message)

                if not plan_response.message.tool_calls:
                    break

                # research_destination is TERMINAL: its guide card IS the turn's
                # answer, so we don't loop back to the LLM (that just re-dumps the
                # report). We defer appending the assistant copy until all tool_use
                # blocks in this response have a tool_result, keeping order valid.
                terminal_report: str | None = None
                for call in plan_response.message.tool_calls:
                    try:
                        if call.name == "research_destination":
                            report = await self._research(call.args.get("query", ""))
                            terminal_report = report.markdown_report
                            result = f"{report.short_summary}\n\n{report.markdown_report}"
                        elif call.name == "add_to_itinerary":
                            result = await self._add_to_itinerary(call, account_key)
                        elif call.name == "remove_from_itinerary":
                            result = self._remove_from_itinerary(call.args.get("item_ids", []))
                        elif call.name == "book_trip":
                            result = await self._book_trip(account_key)
                        elif call.name == "create_invoice":
                            result = await self._create_invoice(call, account_key)
                        else:
                            result = await workflow.execute_activity(
                                execute_tool,
                                ToolRequest(call=call, account_key=account_key),
                                start_to_close_timeout=timedelta(seconds=30),
                                retry_policy=TOOL_RETRY,
                                summary=call.name,
                            )
                    except ActivityError as e:
                        # Terminal tool failure — e.g. the non-retryable business
                        # decline. Hand it back to the model as an error result so
                        # it explains to the traveller; the conversation continues.
                        result = json.dumps({"error": _failure_message(e)})
                        terminal_report = None  # error → let the model explain it
                    self.messages.append(
                        ChatMessage(role="tool", content=result, tool_call_id=call.id)
                    )

                if terminal_report is not None:
                    # The guide renders in the transcript as a plain assistant
                    # message; it also stays in history (the tool result above) so
                    # follow-ups ("add the nonstop flight") are grounded.
                    self.messages.append(ChatMessage(role="assistant", content=terminal_report))
                    break

            self.phase = "idle"
            self.turn_in_progress = False

    @workflow.update
    async def send_message(self, text: str) -> TurnResult:
        """One chat turn: append the message, wake the loop, wait until the
        turn settles — a final reply OR parked on a human (booking approval,
        or research's clarifying questions)."""
        turn_start = len(self.messages)
        self.messages.append(ChatMessage(role="user", content=text))
        self.turn_in_progress = True
        await workflow.wait_condition(
            lambda: not self.turn_in_progress
            or self.pending_confirmation is not None
            or self.pending_clarifications is not None
        )
        reply = self._last_assistant_text(since=turn_start)  # only THIS turn's text
        if self.pending_clarifications is not None:
            return TurnResult(status="awaiting_clarifications", reply=reply)
        if self.pending_confirmation is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)

    @workflow.signal
    def confirm_action(self, decision: ApprovalDecision) -> None:
        """Confirm (or reject) the parked consequential action — a booking or an invoice."""
        self.approval = decision

    @workflow.signal
    def provide_clarifications(self, answers: dict[str, str]) -> None:
        self.clar_answers = answers or {}
        self.answers_submitted = True

    @workflow.signal
    def set_llm_status(self, down: bool) -> None:
        self.llm_down = down

    @workflow.query
    def is_llm_down(self) -> bool:
        return self.llm_down

    @workflow.query
    def transcript(self) -> list[ChatMessage]:
        """Display view: only user/assistant messages with text."""
        return [m for m in self.messages
                if m.role in ("user", "assistant") and m.content]

    @workflow.query
    def pending_approval(self) -> PendingConfirmation | None:
        return self.pending_confirmation

    @workflow.query
    def research_status(self) -> ResearchStatus:
        """Live fan-out view the UI polls: current phase, the search plan, how many
        searches have completed, and any clarifying questions it's waiting on."""
        return ResearchStatus(
            phase=self.phase,
            plan=self.plan,
            searches_total=self.searches_total,
            searches_done=self.searches_done,
            questions=self.pending_clarifications.questions if self.pending_clarifications else [],
        )

    @workflow.query
    def itinerary_view(self) -> list[ItineraryItem]:
        return self.itinerary

    # ── research_destination: plan → parallel search fan-out → write ──
    async def _research(self, query: str) -> ReportData:
        self.plan = []
        self.searches_total = 0
        self.searches_done = 0

        self.phase = "planning"
        plan: SearchPlan = await workflow.execute_activity(
            plan_searches, query,
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=LLM_RETRY, summary="plan",
        )
        self.plan = plan.searches
        self.searches_total = len(self.plan)

        # FAN-OUT: run every planned search as a parallel activity. Kill a worker
        # here and only the unfinished searches re-run — the win over a plain loop.
        self.phase = "searching"

        async def _run_search(item: SearchItem) -> str:
            result = await workflow.execute_activity(
                web_search, item,
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=LLM_RETRY, summary="web_search",
            )
            self.searches_done += 1
            return result

        findings = await asyncio.gather(*[_run_search(s) for s in self.plan])

        self.phase = "writing"
        report: ReportData = await workflow.execute_activity(
            write_report, WriteRequest(brief=query, findings=list(findings)),
            start_to_close_timeout=timedelta(seconds=180),
            retry_policy=LLM_RETRY, summary="synthesize",
        )
        self.phase = "idle"
        return report

    # ── itinerary ──────────────────────────────────────────────────────────────
    async def _add_to_itinerary(self, call: ToolCall, account_key: str) -> str:
        # The activity does the catalog lookup; the WORKFLOW owns itinerary state.
        result = await workflow.execute_activity(
            execute_tool, ToolRequest(call=call, account_key=account_key),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TOOL_RETRY, summary=call.name,
        )
        rows = json.loads(result)
        if isinstance(rows, dict) and rows.get("error"):
            return result
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
        return json.dumps({
            "added": [{"item_id": a.item_id, "title": a.title} for a in added],
            "itinerary_size": len(self.itinerary),
            "itinerary_total": round(sum(i.price for i in self.itinerary), 2),
        })

    def _remove_from_itinerary(self, item_ids: list[str]) -> str:
        ids = set(item_ids or [])
        before = len(self.itinerary)
        self.itinerary = [i for i in self.itinerary if i.item_id not in ids]
        return json.dumps({
            "removed": before - len(self.itinerary),
            "itinerary_size": len(self.itinerary),
            "itinerary_total": round(sum(i.price for i in self.itinerary), 2),
        })

    # ── consequential actions: park on the traveller's confirmation, then settle ──
    async def _await_confirmation(self) -> ApprovalDecision:
        """Durable pause on the confirmation gate — survives worker restarts."""
        await workflow.wait_condition(lambda: self.approval is not None)
        decision, self.approval, self.pending_confirmation = self.approval, None, None
        return decision

    async def _book_trip(self, account_key: str) -> str:
        """Book the whole itinerary. Parks on confirmation, then settles."""
        if not self.itinerary:
            return json.dumps({"error": "The itinerary is empty — add flights, hotels, "
                                        "or activities before booking."})
        items = [{"kind": i.kind, "ref_id": i.ref_id, "title": i.title, "price": i.price}
                 for i in self.itinerary]
        total = round(sum(i.price for i in self.itinerary), 2)
        summary = f"{len(items)} item(s) — ${total:,.2f}"

        self.pending_confirmation = PendingConfirmation(
            action="book_trip", title="Booking approval required",
            detail=summary, amount=total,
            args={"items": [{"title": i.title, "price": i.price} for i in self.itinerary]},
        )
        decision = await self._await_confirmation()
        if not decision.approved:
            reason = f" Reason: {decision.reason}" if decision.reason else ""
            return f"The traveller DECLINED this booking.{reason}"

        book_call = ToolCall(id="book", name="book_trip",
                             args={"items": items, "summary": summary})
        result = await workflow.execute_activity(
            execute_tool, ToolRequest(call=book_call, account_key=account_key),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TOOL_RETRY, summary="book_trip",
        )
        self.itinerary = []  # booked → empty the itinerary
        return result

    async def _create_invoice(self, call: ToolCall, account_key: str) -> str:
        """Invoice one chosen flight (CreateInvoice). Parks on confirmation, then settles."""
        amount = round(float(call.args.get("amount") or 0), 2)
        flight_details = call.args.get("flight_details", "")
        if amount <= 0 or not flight_details:
            return json.dumps({"error": "Need a positive amount and a flight description "
                                        "to create an invoice."})
        self.pending_confirmation = PendingConfirmation(
            action="create_invoice", title="Create invoice",
            detail=flight_details, amount=amount,
            args={"amount": amount, "flight_details": flight_details},
        )
        decision = await self._await_confirmation()
        if not decision.approved:
            reason = f" Reason: {decision.reason}" if decision.reason else ""
            return f"The traveller DECLINED the invoice.{reason}"

        invoice_call = ToolCall(id="invoice", name="create_invoice",
                                args={"amount": amount, "flight_details": flight_details})
        return await workflow.execute_activity(
            execute_tool, ToolRequest(call=invoice_call, account_key=account_key),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=TOOL_RETRY, summary="create_invoice",
        )

    def _last_assistant_text(self, since: int = 0) -> str:
        for m in reversed(self.messages[since:]):
            if m.role == "assistant" and m.content:
                return m.content
        return ""
