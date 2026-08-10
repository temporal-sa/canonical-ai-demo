from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class LLMRequest(BaseModel):
    messages: list[ChatMessage]


class LLMResponse(BaseModel):
    message: ChatMessage


class ToolRequest(BaseModel):
    call: ToolCall
    account_key: str  # conversation-scoped DB identity (the workflow ID), not an email


# ── confirmation gate (human-in-the-loop for consequential/write tools) ──────
class PendingConfirmation(BaseModel):
    """A consequential (write) action parked on the traveller's confirmation —
    booking a trip or creating an invoice. The UI renders the tool name, its
    args, and a Confirm button (the durable wait_condition + signal gate)."""
    action: Literal["book_trip", "create_invoice"]
    title: str
    detail: str = ""
    amount: float = 0.0
    args: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str | None = None


class TurnResult(BaseModel):
    status: Literal["reply", "awaiting_approval"]
    reply: str


# ── destination research pipeline (plan → fan-out search → write) ─────────────
# One research pass is: plan N focused searches, run them in PARALLEL as
# activities, then synthesize a cited destination guide.
class SearchItem(BaseModel):
    query: str
    reason: str


class SearchPlan(BaseModel):
    searches: list[SearchItem] = Field(default_factory=list)


class WriteRequest(BaseModel):
    brief: str
    findings: list[str]


class ReportData(BaseModel):
    short_summary: str
    markdown_report: str


class ResearchStatus(BaseModel):
    """Live view the UI polls to watch the research fan-out unfold."""
    phase: str = "idle"           # idle · planning · searching · writing
    plan: list[SearchItem] = Field(default_factory=list)
    searches_total: int = 0
    searches_done: int = 0


# ── itinerary (workflow-durable, conversation-scoped) ────────────────────────
# The itinerary is the travel analog of a shopping cart: a durable list the
# traveller builds up across the conversation. Items are heterogeneous — a
# flight, a hotel stay, or an activity — so each carries its own kind + ref_id.
class ItineraryItem(BaseModel):
    kind: Literal["flight", "hotel", "activity"]
    ref_id: int
    title: str
    subtitle: str = ""
    price: float = 0.0

    @property
    def item_id(self) -> str:
        return f"{self.kind}-{self.ref_id}"
