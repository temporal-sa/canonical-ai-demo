package travelagent

import "encoding/json"

// Gateway-facing DTOs intentionally use snake_case JSON keys. The shared
// Python gateway reads these fields directly; see ../CONTRACT.md.

type ToolCall struct {
	ID   string         `json:"id"`
	Name string         `json:"name"`
	Args map[string]any `json:"args"`
}

type ChatMessage struct {
	Role       string     `json:"role"`
	Content    string     `json:"content"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID *string    `json:"tool_call_id,omitempty"`
}

type TurnResult struct {
	Status string `json:"status"`
	Reply  string `json:"reply"`
}

type ApprovalDecision struct {
	Approved bool    `json:"approved"`
	Reason   *string `json:"reason"`
}

type PendingConfirmation struct {
	Action string         `json:"action"`
	Title  string         `json:"title"`
	Detail string         `json:"detail"`
	Amount float64        `json:"amount"`
	Args   map[string]any `json:"args"`
}

type SearchItem struct {
	Query  string `json:"query"`
	Reason string `json:"reason"`
}

type ResearchStatus struct {
	Phase         string       `json:"phase"`
	Plan          []SearchItem `json:"plan"`
	SearchesTotal int          `json:"searches_total"`
	SearchesDone  int          `json:"searches_done"`
}

type ItineraryItem struct {
	Kind     string  `json:"kind"`
	RefID    int64   `json:"ref_id"`
	Title    string  `json:"title"`
	Subtitle string  `json:"subtitle"`
	Price    float64 `json:"price"`
}

type CheckoutRequest struct {
	AccountKey string          `json:"account_key"`
	Items      []ItineraryItem `json:"items"`
	Summary    string          `json:"summary"`
}

type CheckoutStepRequest struct {
	AccountKey string        `json:"account_key"`
	Item       ItineraryItem `json:"item"`
}

type CheckoutReservation struct {
	Kind          string `json:"kind"`
	RefID         int64  `json:"ref_id"`
	Title         string `json:"title"`
	ReservationID string `json:"reservation_id"`
	Status        string `json:"status"`
}

type CheckoutResult struct {
	Status        string                `json:"status"`
	Message       string                `json:"message"`
	WorkflowID    string                `json:"workflow_id"`
	Reservations  []CheckoutReservation `json:"reservations"`
	Compensations []CheckoutReservation `json:"compensations"`
	Failure       *string               `json:"failure"`
	BookingID     *int64                `json:"booking_id"`
}

type FinalizeCheckoutResult struct {
	BookingID int64 `json:"booking_id"`
}

type LLMRequest struct {
	Messages []ChatMessage `json:"messages"`
}

type LLMResponse struct {
	Message ChatMessage `json:"message"`
}

type ToolRequest struct {
	Call       ToolCall `json:"call"`
	AccountKey string   `json:"account_key"`
}

type SearchPlan struct {
	Searches []SearchItem `json:"searches"`
}

type WriteRequest struct {
	Brief    string   `json:"brief"`
	Findings []string `json:"findings"`
}

type ReportData struct {
	ShortSummary   string `json:"short_summary"`
	MarkdownReport string `json:"markdown_report"`
}

type ToolDefinition struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"input_schema"`
}

type anthropicMessage struct {
	Role    string `json:"role"`
	Content any    `json:"content"`
}

type anthropicResponse struct {
	Content    []json.RawMessage `json:"content"`
	StopReason string            `json:"stop_reason"`
}

type anthropicBlock struct {
	Type  string          `json:"type"`
	Text  string          `json:"text"`
	ID    string          `json:"id"`
	Name  string          `json:"name"`
	Input json.RawMessage `json:"input"`
}
