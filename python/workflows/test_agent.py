"""TravelAgentWorkflow against stub LLM and tool Activities: no API key, no DB.

The workflow runs unsandboxed so a test can shrink a guard-rail constant (the
step limit, the timeouts) and see it trip in seconds. The replay test at the end
runs sandboxed, as production does, to prove the histories replay deterministically.
"""

import asyncio
import json
import shutil
import unittest
from collections import deque
from datetime import timedelta
from unittest import mock

from temporalio import activity
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

import config
from models.types import (
    ApprovalDecision,
    ChatMessage,
    LLMRequest,
    LLMResponse,
    ReportData,
    SearchItem,
    SearchPlan,
    ToolCall,
    ToolRequest,
    WriteRequest,
)
from workflows import agent
from workflows.agent import TravelAgentWorkflow
from workflows.checkout import CheckoutWorkflow

TASK_QUEUE = "agent-test"

# Each call_llm pops the next entry: an LLMResponse to return, an exception to
# raise, or a function of the request. An empty script answers "done".
LLM_SCRIPT: deque = deque()
TOOL_CALLS: list[ToolRequest] = []


def say(text: str) -> LLMResponse:
    return LLMResponse(message=ChatMessage(role="assistant", content=text))


def use(name: str, **args) -> LLMResponse:
    return LLMResponse(message=ChatMessage(
        role="assistant", tool_calls=[ToolCall(id=f"call-{name}", name=name, args=args)]))


@activity.defn(name="call_llm")
async def stub_llm(req: LLMRequest) -> LLMResponse:
    step = LLM_SCRIPT.popleft() if LLM_SCRIPT else say("done")
    if isinstance(step, Exception):
        LLM_SCRIPT.appendleft(step)  # keep failing on every retry
        raise step
    return step(req) if callable(step) else step


@activity.defn(name="execute_tool")
async def stub_tool(req: ToolRequest) -> str:
    TOOL_CALLS.append(req)
    if req.call.name == "add_to_itinerary":
        return json.dumps([{"kind": "flight", "ref_id": 1, "title": "Demo Air", "price": 100}])
    if req.call.name == "create_invoice":
        return json.dumps({"invoice_id": 1, "status": "invoiced"})
    return "[]"


# Research: three searches, one of which ("down") fails for good.
@activity.defn(name="plan_searches")
async def stub_plan(brief: str) -> SearchPlan:
    return SearchPlan(searches=[SearchItem(query=q, reason="test") for q in ("food", "down", "trips")])


@activity.defn(name="web_search")
async def stub_search(item: SearchItem) -> str:
    if item.query == "down":
        raise ApplicationError("out of budget", type="LLMFatalError", non_retryable=True)
    return f"found {item.query}"


@activity.defn(name="write_report")
async def stub_write(req: WriteRequest) -> ReportData:
    return ReportData(short_summary="guide", markdown_report="; ".join(req.findings))


class AgentWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporal_path = shutil.which("temporal")
        if temporal_path is None:
            self.skipTest("Temporal CLI is required for workflow tests")
        self.env = await WorkflowEnvironment.start_local(
            data_converter=pydantic_data_converter,
            dev_server_existing_path=temporal_path,
            dev_server_log_level="error",
        )
        self.client: Client = self.env.client
        LLM_SCRIPT.clear()
        TOOL_CALLS.clear()
        self.worker = Worker(
            self.client,
            task_queue=TASK_QUEUE,
            workflows=[TravelAgentWorkflow, CheckoutWorkflow],
            activities=[stub_llm, stub_tool, stub_plan, stub_search, stub_write],
            workflow_runner=UnsandboxedWorkflowRunner(),
        )
        self.worker_task = asyncio.create_task(self.worker.run())

    async def asyncTearDown(self) -> None:
        await self.worker.shutdown()
        await self.worker_task
        await self.env.shutdown()

    async def _start(self, workflow_id: str):
        return await self.client.start_workflow(
            TravelAgentWorkflow.run, "traveller@example.com", id=workflow_id, task_queue=TASK_QUEUE
        )

    async def _send(self, workflow_id: str, text: str):
        # A fresh handle follows the latest run, across continue-as-new.
        return await self.client.get_workflow_handle(workflow_id).execute_update(
            TravelAgentWorkflow.send_message, text)

    async def _settled(self, workflow_id: str) -> list[ChatMessage]:
        """Wait for the turn after an approval to finish; return the transcript."""
        handle = self.client.get_workflow_handle(workflow_id)
        for _ in range(100):
            transcript = await handle.query(TravelAgentWorkflow.transcript)
            if transcript and transcript[-1].role == "assistant":
                return transcript
            await asyncio.sleep(0.1)
        self.fail("turn never settled")

    async def test_a_stray_approval_cannot_approve_the_next_action(self) -> None:
        handle = await self._start("agent-stray-approval")
        await handle.signal(TravelAgentWorkflow.confirm_action, ApprovalDecision(approved=True))
        LLM_SCRIPT.append(use("create_invoice", amount=250, flight_details="DA101"))

        result = await self._send("agent-stray-approval", "Invoice me for that flight")

        self.assertEqual("awaiting_approval", result.status)  # it waited for a human
        self.assertEqual([], TOOL_CALLS)

    async def test_messages_are_rejected_while_an_approval_is_pending(self) -> None:
        await self._start("agent-busy")
        LLM_SCRIPT.append(use("create_invoice", amount=250, flight_details="DA101"))
        await self._send("agent-busy", "Invoice me")

        with self.assertRaises(WorkflowUpdateFailedError) as raised:
            await self._send("agent-busy", "hello?")
        self.assertIn("Approve or decline", str(raised.exception.cause))

    async def test_approved_invoice_carries_a_workflow_minted_idempotency_key(self) -> None:
        handle = await self._start("agent-invoice")
        LLM_SCRIPT.extend([use("create_invoice", amount=250, flight_details="DA101"),
                           say("Invoiced.")])
        await self._send("agent-invoice", "Invoice me")
        await handle.signal(TravelAgentWorkflow.confirm_action, ApprovalDecision(approved=True))
        await self._settled("agent-invoice")

        self.assertEqual(["create_invoice"], [c.call.name for c in TOOL_CALLS])
        self.assertEqual("agent-invoice-invoice-1", TOOL_CALLS[0].call.args["idempotency_key"])

    async def test_an_unanswered_approval_expires_as_declined(self) -> None:
        seen: list[str] = []

        def record_tool_result(req: LLMRequest) -> LLMResponse:
            seen.append(req.messages[-1].content)
            return say("No invoice, then.")

        await self._start("agent-expiry")
        LLM_SCRIPT.extend([use("create_invoice", amount=250, flight_details="DA101"),
                           record_tool_result])
        with mock.patch.object(agent, "APPROVAL_TIMEOUT", timedelta(seconds=1)):
            await self._send("agent-expiry", "Invoice me")
            await self._settled("agent-expiry")

        self.assertIn("DECLINED", seen[0])
        self.assertIn("expired", seen[0])
        self.assertEqual([], TOOL_CALLS)

    async def test_a_fatal_llm_error_ends_the_turn_with_an_apology(self) -> None:
        await self._start("agent-fatal")
        LLM_SCRIPT.append(ApplicationError("bad key", type="LLMFatalError", non_retryable=True))

        result = await self._send("agent-fatal", "Hi")

        self.assertIn("sorry", result.reply)

    async def test_an_unclassified_llm_error_gives_up_within_the_budget(self) -> None:
        await self._start("agent-budget")
        # What a missing API key looks like: a client-side error nobody classified.
        LLM_SCRIPT.append(TypeError("Could not resolve authentication method"))

        with mock.patch.object(agent, "LLM_BUDGET", timedelta(seconds=3)):
            result = await asyncio.wait_for(self._send("agent-budget", "Hi"), timeout=30)

        self.assertIn("sorry", result.reply)

    async def test_research_writes_the_guide_from_the_searches_that_came_back(self) -> None:
        await self._start("agent-research")
        LLM_SCRIPT.append(use("research_destination", query="Tokyo"))

        result = await self._send("agent-research", "Research Tokyo")

        self.assertEqual("found food; found trips", result.reply)

    async def test_a_runaway_tool_loop_stops_at_the_step_limit(self) -> None:
        await self._start("agent-runaway")
        LLM_SCRIPT.extend(use("search_flights", destination="Tokyo") for _ in range(10))

        with mock.patch.object(agent, "MAX_STEPS_PER_TURN", 3):
            result = await self._send("agent-runaway", "Find me every flight")

        self.assertIn("narrow down", result.reply)
        self.assertEqual(3, len(TOOL_CALLS))

    async def test_continue_as_new_carries_the_conversation_forward(self) -> None:
        first_run = (await self._start("agent-can")).result_run_id
        LLM_SCRIPT.extend([use("add_to_itinerary", items=[{"kind": "flight", "ref_id": 1}]),
                           say("Added the flight.")])

        with mock.patch.object(agent, "CONTINUE_AS_NEW_AFTER_EVENTS", 1):
            await self._send("agent-can", "Add the flight")
            handle = self.client.get_workflow_handle("agent-can")
            for _ in range(50):
                if (await handle.describe()).run_id != first_run:
                    break
                await asyncio.sleep(0.1)
            second = await self._send("agent-can", "What's in my trip?")

        latest = self.client.get_workflow_handle("agent-can")
        self.assertNotEqual(first_run, (await latest.describe()).run_id)
        self.assertEqual(["Demo Air"],
                         [i.title for i in await latest.query(TravelAgentWorkflow.itinerary_view)])
        transcript = await latest.query(TravelAgentWorkflow.transcript)
        self.assertEqual(["Add the flight", "Added the flight.", "What's in my trip?", "done"],
                         [m.content for m in transcript])
        self.assertEqual("done", second.reply)

    async def test_an_idle_conversation_closes(self) -> None:
        with mock.patch.object(agent, "IDLE_TIMEOUT", timedelta(seconds=1)):
            handle = await self._start("agent-idle")
            await asyncio.wait_for(handle.result(), timeout=10)

    async def test_histories_replay_deterministically(self) -> None:
        handle = await self._start("agent-replay")
        await handle.signal(TravelAgentWorkflow.confirm_action, ApprovalDecision(approved=True))
        LLM_SCRIPT.extend([use("add_to_itinerary", items=[{"kind": "flight", "ref_id": 1}]),
                           say("Added."),
                           use("create_invoice", amount=100, flight_details="Demo Air"),
                           say("Invoiced.")])
        await self._send("agent-replay", "Add the flight")
        await self._send("agent-replay", "Invoice me")
        await handle.signal(TravelAgentWorkflow.confirm_action, ApprovalDecision(approved=True))
        await self._settled("agent-replay")

        await Replayer(
            workflows=[TravelAgentWorkflow, CheckoutWorkflow],
            data_converter=pydantic_data_converter,
        ).replay_workflow(await handle.fetch_history())


class WorkerConfigTests(unittest.TestCase):
    def test_the_chat_providers_key_is_required(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}, clear=True), \
                mock.patch.object(config, "LLM_PROVIDER", "openai"):
            self.assertEqual("OPENAI_API_KEY", config.missing_llm_key())
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}, clear=True), \
                mock.patch.object(config, "LLM_PROVIDER", "anthropic"):
            self.assertIsNone(config.missing_llm_key())

    def test_research_without_a_claude_key_fails_without_retrying(self) -> None:
        from activities import research
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ApplicationError) as raised:
                research._client()
        self.assertTrue(raised.exception.non_retryable)


if __name__ == "__main__":
    unittest.main()
