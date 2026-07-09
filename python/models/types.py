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
    customer_email: str


class PendingPurchase(BaseModel):
    track_ids: list[int]
    description: str | None = None


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str | None = None


class TurnResult(BaseModel):
    status: Literal["reply", "awaiting_approval"]
    reply: str
