// Wire DTOs for the SDK contract (see ../CONTRACT.md).
//
// ⚠️ snake_case ON PURPOSE. The Python gateway reads these keys directly
// (`searches_total`, `ref_id`, `tool_call_id`, …). TypeScript's instinct is
// camelCase — do NOT rename these fields, the wire contract is the boss.

export type Role = 'system' | 'user' | 'assistant' | 'tool';

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface ChatMessage {
  role: Role;
  content: string;
  // Internal-only; the gateway's /transcript reads role + content only.
  tool_calls?: ToolCall[];
  tool_call_id?: string | null;
}

export interface TurnResult {
  status: 'reply' | 'awaiting_approval';
  reply: string;
}

export interface ApprovalDecision {
  approved: boolean;
  reason?: string | null;
}

export interface PendingConfirmation {
  action: 'book_trip' | 'create_invoice';
  title: string;
  detail: string;
  amount: number;
  args: Record<string, unknown>;
}

export interface SearchItem {
  query: string;
  reason: string;
}

export interface ResearchStatus {
  phase: string; // idle · planning · searching · writing
  plan: SearchItem[];
  searches_total: number;
  searches_done: number;
}

export interface ItineraryItem {
  kind: 'flight' | 'hotel' | 'activity';
  ref_id: number;
  title: string;
  subtitle: string;
  price: number;
}

// ── activity-boundary DTOs (internal to the TS worker; never cross to the
//    gateway, so plain field names are fine — they mirror models/types.py). ──

export interface LLMRequest {
  messages: ChatMessage[];
}

export interface LLMResponse {
  message: ChatMessage;
}

export interface ToolRequest {
  call: ToolCall;
  account_key: string; // conversation-scoped DB identity (the workflow ID)
}

export interface SearchPlan {
  searches: SearchItem[];
}

export interface WriteRequest {
  brief: string;
  findings: string[];
}

export interface ReportData {
  short_summary: string;
  markdown_report: string;
}
