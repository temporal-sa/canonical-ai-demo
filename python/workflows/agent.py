"""SupportAgentWorkflow — the durable agentic ReAct loop.

This file IS the demo. The numbered comments are slide 28's five primitives:
  01 Receive Input · 02 Plan · 03 Execute Tools · 04 Persist State · 05 Loop/Terminate

The agentic loop is just a `while` loop — Temporal makes it durable,
retryable, and pausable-for-humans.
"""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from activities.llm import call_llm
    from activities.tools import execute_tool
    from models.types import (
        ApprovalDecision,
        ChatMessage,
        LLMRequest,
        PendingPurchase,
        ToolRequest,
        TurnResult,
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
    non_retryable_error_types=["PurchaseDeclined"],
)


def _failure_message(e: ActivityError) -> str:
    return getattr(e.cause, "message", None) or "That action could not be completed."


@workflow.defn
class SupportAgentWorkflow:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = [] 
        self.pending_purchase: PendingPurchase | None = None
        self.approval: ApprovalDecision | None = None
        self.turn_in_progress: bool = False
        self.llm_down: bool = False  # demo kill-switch, scoped to THIS conversation

    @workflow.run
    async def run(self, customer_email: str) -> None:
        self.messages.append(ChatMessage(role="system", content=system_prompt(customer_email)))

        # DB identity is the workflow ID, NOT the customer email. Everything the
        # agent persists (orders, purchase history) is scoped to THIS conversation:
        # a new conversation is a new workflow ID = a clean slate. So there is no
        # cross-session memory, and back-to-back demos never see each other's data —
        # no reset or reseed needed. customer_email stays the real, authenticated
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

                for call in plan_response.message.tool_calls:
                    try:
                        if call.name == "purchase_tracks":
                            self.pending_purchase = PendingPurchase(
                                track_ids=call.args.get("track_ids", []),
                                description=call.args.get("summary"),
                            )
                            await workflow.wait_condition(lambda: self.approval is not None)
                            decision, self.approval, self.pending_purchase = self.approval, None, None

                            if not decision.approved:
                                reason = f" Reason: {decision.reason}" if decision.reason else ""
                                result = f"The customer's approver DECLINED this purchase.{reason}"
                            else:
                                result = await workflow.execute_activity(
                                    execute_tool,
                                    ToolRequest(call=call, account_key=account_key),
                                    start_to_close_timeout=timedelta(seconds=30),
                                    retry_policy=TOOL_RETRY,
                                    summary=call.name,
                                )
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
                        # it explains to the customer; the conversation continues.
                        result = json.dumps({"error": _failure_message(e)})
                    self.messages.append(
                        ChatMessage(role="tool", content=result, tool_call_id=call.id)
                    )

            self.turn_in_progress = False
    

    @workflow.update
    async def send_message(self, text: str) -> TurnResult:
        """One chat turn: append the message, wake the loop, wait until the
        turn settles — a final reply OR parked on a purchase approval."""
        turn_start = len(self.messages)
        self.messages.append(ChatMessage(role="user", content=text))
        self.turn_in_progress = True
        await workflow.wait_condition(
            lambda: not self.turn_in_progress or self.pending_purchase is not None
        )
        reply = self._last_assistant_text(since=turn_start)  # only THIS turn's text
        if self.pending_purchase is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)

    @workflow.signal
    def approve_purchase(self, decision: ApprovalDecision) -> None:
        self.approval = decision

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
    def pending_approval(self) -> PendingPurchase | None:
        return self.pending_purchase

    def _last_assistant_text(self, since: int = 0) -> str:
        for m in reversed(self.messages[since:]):
            if m.role == "assistant" and m.content:
                return m.content
        return ""
