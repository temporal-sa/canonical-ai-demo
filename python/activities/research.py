"""The research_destination pipeline's LLM steps, each a Temporal Activity.

Native Claude — no agent framework. Two shapes:
  • structured steps (clarify / enrich / plan / write) force a JSON-schema
    response via `output_config.format` and parse it.
  • the search step hands Claude its built-in `web_search` server tool and
    collects the summary it writes. This is the demo's LIVE data: destination
    intelligence comes off the real web, while flights/hotels are seeded.

Retry philosophy matches activities/llm.py: the SDK's own retries are OFF
(max_retries=0) so Temporal owns ALL retries — every rate-limit or outage shows
as a retry in workflow history. Provider-rejected requests (bad auth/request)
are non-retryable; retrying can't fix those.

These honor the SAME per-conversation kill-switch as call_llm (control.llm_down),
so flipping the Demo-controls outage toggle mid-research makes the whole fan-out
ride out the outage and recover.
"""

import json

import anthropic
from temporalio import activity
from temporalio.exceptions import ApplicationError

import config
import prompts
from . import control
from models.types import (
    ClarifyResult,
    EnrichRequest,
    ReportData,
    SearchItem,
    SearchPlan,
    WriteRequest,
)

# The web_search server tool. We use the BASIC variant (web_search_20250305) on
# purpose: the newer web_search_20260209 does "dynamic filtering" by spinning up a
# code-execution sandbox per search, which adds many seconds — too slow to watch in
# a live demo. Basic returns results directly and is much snappier.
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": config.WEB_SEARCH_MAX_USES,
}

_FATAL = (
    anthropic.BadRequestError,
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
)


async def _guard() -> None:
    """Demo kill-switch (the Demo-controls 'API status' panel). While flipped to
    'down', raise a RETRYABLE error → Temporal retries with backoff until it's
    flipped back, and the retries show in the history."""
    if await control.llm_down():
        raise ApplicationError(
            "LLM provider is unavailable (simulated outage).", type="LLMProviderDown"
        )


def _client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(max_retries=0)


async def _structured(system: str, user: str, schema: dict,
                      max_tokens: int = 2048, effort: str = "low") -> dict:
    """One structured-output call: Claude must answer with JSON matching `schema`.
    Low effort by default keeps these planning/synthesis steps snappy for demos."""
    try:
        async with _client() as client:
            resp = await client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            )
    except _FATAL as e:
        raise ApplicationError(
            f"LLM request rejected: {e}", type="LLMFatalError", non_retryable=True
        ) from e
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


async def _text(system: str, user: str, max_tokens: int = 1024, effort: str = "low") -> str:
    try:
        async with _client() as client:
            resp = await client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort},
            )
    except _FATAL as e:
        raise ApplicationError(
            f"LLM request rejected: {e}", type="LLMFatalError", non_retryable=True
        ) from e
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# ── clarify (human-in-the-loop) ──────────────────────────────────────────────
@activity.defn
async def plan_clarifications(query: str) -> ClarifyResult:
    await _guard()
    data = await _structured(prompts.CLARIFY_SYSTEM, query, prompts.CLARIFY_SCHEMA)
    return ClarifyResult(
        needs_clarification=bool(data.get("needs_clarification")) and bool(data.get("questions")),
        questions=data.get("questions", [])[:3],
    )


@activity.defn
async def enrich_query(req: EnrichRequest) -> str:
    await _guard()
    if not req.answers:
        return req.query
    qa = "\n".join(f"Q: {q}\nA: {a}" for q, a in req.answers.items())
    user = f"Original request:\n{req.query}\n\nClarifications:\n{qa}"
    return await _text(prompts.ENRICH_SYSTEM, user)


# ── plan ─────────────────────────────────────────────────────────────────────
@activity.defn
async def plan_searches(brief: str) -> SearchPlan:
    await _guard()
    system = prompts.plan_system(config.RESEARCH_SEARCHES)
    data = await _structured(system, f"Research brief:\n{brief}", prompts.PLAN_SCHEMA)
    searches = [SearchItem(**s) for s in data.get("searches", [])]
    return SearchPlan(searches=searches)


# ── search (native web_search tool) ──────────────────────────────────────────
@activity.defn
async def web_search(item: SearchItem) -> str:
    """One durable search. If the worker dies mid-fan-out, only the searches
    that hadn't completed re-run on restart — finished ones are already in the
    workflow history."""
    await _guard()
    user = (
        f"Search query: {item.query}\n"
        f"Why this matters: {item.reason}\n\n"
        "Search the web and summarize the most relevant findings."
    )
    messages: list[dict] = [{"role": "user", "content": user}]

    # Server-side tool loop: Claude may pause (pause_turn) if it hits the
    # per-turn tool-use cap — re-send to let it resume, with a hard cap.
    try:
        async with _client() as client:
            for _ in range(4):
                resp = await client.messages.create(
                    model=config.ANTHROPIC_MODEL,
                    max_tokens=1024,
                    system=prompts.SEARCH_SYSTEM,
                    tools=[WEB_SEARCH_TOOL],
                    output_config={"effort": "low"},
                    messages=messages,
                )
                if resp.stop_reason != "pause_turn":
                    break
                messages.append({"role": "assistant", "content": resp.content})
    except _FATAL as e:
        raise ApplicationError(
            f"LLM request rejected: {e}", type="LLMFatalError", non_retryable=True
        ) from e

    summary = "".join(b.text for b in resp.content if b.type == "text").strip()
    return f"### {item.query}\n{summary}" if summary else f"### {item.query}\n(no findings)"


# ── write ────────────────────────────────────────────────────────────────────
@activity.defn
async def write_report(req: WriteRequest) -> ReportData:
    await _guard()
    findings = "\n\n".join(req.findings)
    user = f"Research brief:\n{req.brief}\n\nFindings from web searches:\n\n{findings}"
    data = await _structured(prompts.WRITE_SYSTEM, user, prompts.WRITE_SCHEMA, max_tokens=1024, effort="low")
    return ReportData(
        short_summary=data.get("short_summary", ""),
        markdown_report=data.get("markdown_report", ""),
        follow_up_questions=data.get("follow_up_questions", [])[:3],
    )
