package travelagent

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"strings"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
)

// Activities owns every side effect used by the workflows: Anthropic HTTP,
// Postgres, and the checkout provider stand-ins. Workflow code stays pure.
type Activities struct {
	cfg      Config
	db       *DB
	temporal client.Client
	http     *http.Client
}

func NewActivities(cfg Config, db *DB, temporalClient client.Client) *Activities {
	return &Activities{cfg: cfg, db: db, temporal: temporalClient, http: &http.Client{Timeout: 55 * time.Second}}
}

func (a *Activities) llmDown(ctx context.Context) bool {
	info := activity.GetInfo(ctx)
	if info.WorkflowExecution.ID == "" {
		return false
	}
	value, err := a.temporal.QueryWorkflow(ctx, info.WorkflowExecution.ID, "", "is_llm_down")
	if err != nil {
		return false
	}
	var down bool
	return value.Get(&down) == nil && down
}

func (a *Activities) guardLLM(ctx context.Context) error {
	if a.llmDown(ctx) {
		return temporal.NewApplicationError("LLM provider is unavailable (simulated outage).", "LLMProviderDown")
	}
	if a.cfg.AnthropicAPIKey == "" {
		return temporal.NewNonRetryableApplicationError("ANTHROPIC_API_KEY is required", "LLMFatalError", nil)
	}
	return nil
}

func (a *Activities) anthropic(ctx context.Context, body map[string]any) (anthropicResponse, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return anthropicResponse{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.cfg.AnthropicMessagesURL, bytes.NewReader(payload))
	if err != nil {
		return anthropicResponse{}, err
	}
	req.Header.Set("content-type", "application/json")
	req.Header.Set("anthropic-version", "2023-06-01")
	req.Header.Set("x-api-key", a.cfg.AnthropicAPIKey)
	resp, err := a.http.Do(req)
	if err != nil {
		return anthropicResponse{}, err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return anthropicResponse{}, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		message := fmt.Sprintf("Anthropic returned HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
		if resp.StatusCode == 400 || resp.StatusCode == 401 || resp.StatusCode == 403 || resp.StatusCode == 404 {
			return anthropicResponse{}, temporal.NewNonRetryableApplicationError(message, "LLMFatalError", nil)
		}
		return anthropicResponse{}, errors.New(message)
	}
	var result anthropicResponse
	if err := json.Unmarshal(raw, &result); err != nil {
		return anthropicResponse{}, fmt.Errorf("decode Anthropic response: %w", err)
	}
	return result, nil
}

func (a *Activities) CallLLM(ctx context.Context, req LLMRequest) (LLMResponse, error) {
	if err := a.guardLLM(ctx); err != nil {
		return LLMResponse{}, err
	}
	system := ""
	messages := make([]anthropicMessage, 0, len(req.Messages))
	for _, message := range req.Messages {
		switch message.Role {
		case "system":
			system = message.Content
		case "user":
			messages = append(messages, anthropicMessage{Role: "user", Content: message.Content})
		case "assistant":
			blocks := make([]any, 0, 1+len(message.ToolCalls))
			if message.Content != "" {
				blocks = append(blocks, map[string]any{"type": "text", "text": message.Content})
			}
			for _, call := range message.ToolCalls {
				blocks = append(blocks, map[string]any{"type": "tool_use", "id": call.ID, "name": call.Name, "input": call.Args})
			}
			messages = append(messages, anthropicMessage{Role: "assistant", Content: blocks})
		case "tool":
			id := ""
			if message.ToolCallID != nil {
				id = *message.ToolCallID
			}
			block := map[string]any{"type": "tool_result", "tool_use_id": id, "content": message.Content}
			messages = append(messages, anthropicMessage{Role: "user", Content: []any{block}})
		}
	}
	resp, err := a.anthropic(ctx, map[string]any{
		"model": a.cfg.AnthropicModel, "max_tokens": 2048, "system": system,
		"messages": messages, "tools": Tools,
	})
	if err != nil {
		return LLMResponse{}, err
	}
	out := ChatMessage{Role: "assistant", ToolCalls: []ToolCall{}}
	for _, raw := range resp.Content {
		var block anthropicBlock
		if err := json.Unmarshal(raw, &block); err != nil {
			return LLMResponse{}, err
		}
		switch block.Type {
		case "text":
			out.Content += block.Text
		case "tool_use":
			args := map[string]any{}
			if len(block.Input) > 0 {
				_ = json.Unmarshal(block.Input, &args)
			}
			out.ToolCalls = append(out.ToolCalls, ToolCall{ID: block.ID, Name: block.Name, Args: args})
		}
	}
	return LLMResponse{Message: out}, nil
}

func (a *Activities) structured(ctx context.Context, system, user string, schema map[string]any, maxTokens int) (map[string]any, error) {
	resp, err := a.anthropic(ctx, map[string]any{
		"model": a.cfg.AnthropicModel, "max_tokens": maxTokens, "system": system,
		"messages":      []anthropicMessage{{Role: "user", Content: user}},
		"output_config": map[string]any{"effort": "low", "format": map[string]any{"type": "json_schema", "schema": schema}},
	})
	if err != nil {
		return nil, err
	}
	text := ""
	for _, raw := range resp.Content {
		var block anthropicBlock
		if json.Unmarshal(raw, &block) == nil && block.Type == "text" {
			text += block.Text
		}
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(text), &result); err != nil {
		return nil, fmt.Errorf("decode structured LLM response: %w", err)
	}
	return result, nil
}

func (a *Activities) PlanSearches(ctx context.Context, brief string) (SearchPlan, error) {
	if err := a.guardLLM(ctx); err != nil {
		return SearchPlan{}, err
	}
	data, err := a.structured(ctx, PlanSystem(a.cfg.ResearchSearches), "Research brief:\n"+brief, PlanSchema, 2048)
	if err != nil {
		return SearchPlan{}, err
	}
	result := SearchPlan{Searches: []SearchItem{}}
	for _, raw := range sliceValue(data["searches"]) {
		m, _ := raw.(map[string]any)
		result.Searches = append(result.Searches, SearchItem{Query: stringValue(m["query"]), Reason: stringValue(m["reason"])})
	}
	return result, nil
}

func (a *Activities) WebSearch(ctx context.Context, item SearchItem) (string, error) {
	if err := a.guardLLM(ctx); err != nil {
		return "", err
	}
	if activity.GetInfo(ctx).Attempt == 1 && rand.Float64() < a.cfg.WebSearchFailRate {
		return "", temporal.NewApplicationError("web_search transient failure (simulated) for "+item.Query, "WebSearchFlaky")
	}
	messages := []anthropicMessage{{Role: "user", Content: fmt.Sprintf("Search query: %s\nWhy this matters: %s\n\nSearch the web and summarize the most relevant findings.", item.Query, item.Reason)}}
	var resp anthropicResponse
	var err error
	for range 4 {
		resp, err = a.anthropic(ctx, map[string]any{
			"model": a.cfg.AnthropicModel, "max_tokens": 1024, "system": SearchSystem,
			"messages":      messages,
			"tools":         []any{map[string]any{"type": "web_search_20250305", "name": "web_search", "max_uses": a.cfg.WebSearchMaxUses}},
			"output_config": map[string]any{"effort": "low"},
		})
		if err != nil {
			return "", err
		}
		if resp.StopReason != "pause_turn" {
			break
		}
		messages = append(messages, anthropicMessage{Role: "assistant", Content: resp.Content})
	}
	parts := []string{}
	for _, raw := range resp.Content {
		var block anthropicBlock
		if json.Unmarshal(raw, &block) == nil && block.Type == "text" {
			parts = append(parts, block.Text)
		}
	}
	summary := strings.TrimSpace(strings.Join(parts, ""))
	if summary == "" {
		summary = "(no findings)"
	}
	return "### " + item.Query + "\n" + summary, nil
}

func (a *Activities) WriteReport(ctx context.Context, req WriteRequest) (ReportData, error) {
	if err := a.guardLLM(ctx); err != nil {
		return ReportData{}, err
	}
	user := "Research brief:\n" + req.Brief + "\n\nFindings from web searches:\n\n" + strings.Join(req.Findings, "\n\n")
	data, err := a.structured(ctx, WriteSystem, user, WriteSchema, 2500)
	if err != nil {
		return ReportData{}, err
	}
	return ReportData{ShortSummary: stringValue(data["short_summary"]), MarkdownReport: stringValue(data["markdown_report"])}, nil
}

func (a *Activities) ExecuteTool(ctx context.Context, req ToolRequest) (string, error) {
	if a.cfg.ToolDelay > 0 {
		time.Sleep(a.cfg.ToolDelay)
	}
	args := req.Call.Args
	var result any
	var err error
	switch req.Call.Name {
	case "search_events":
		result, err = a.db.SearchEvents(ctx, stringValue(args["destination"]), args["month"])
	case "search_destinations":
		result, err = a.db.SearchDestinations(ctx, stringValue(args["query"]))
	case "get_destination_info":
		result, err = a.db.GetDestinationInfo(ctx, stringValue(args["destination"]))
	case "search_flights":
		result, err = a.db.SearchFlights(ctx, stringValue(args["destination"]), stringValue(args["origin"]), stringValue(args["depart_date"]))
	case "search_hotels":
		var maxPrice *float64
		if value, ok := args["max_price"]; ok {
			n := floatValue(value)
			maxPrice = &n
		}
		result, err = a.db.SearchHotels(ctx, stringValue(args["destination"]), maxPrice)
	case "search_attractions":
		result, err = a.db.SearchAttractions(ctx, stringValue(args["destination"]))
	case "get_bookings":
		result, err = a.db.GetBookings(ctx, req.AccountKey)
	case "get_booking_details":
		result, err = a.db.GetBookingDetails(ctx, int64Value(args["booking_id"]))
	case "add_to_itinerary":
		result, err = a.db.GetItineraryItems(ctx, mapSlice(args["items"]))
	case "create_invoice":
		result, err = a.db.RecordInvoice(ctx, req.AccountKey, floatValue(args["amount"]), stringValue(args["flight_details"]))
	default:
		return "", temporal.NewNonRetryableApplicationError("Unknown tool: "+req.Call.Name, "UnknownTool", nil)
	}
	if err != nil {
		if business, ok := businessError(err); ok {
			encoded, _ := json.Marshal(map[string]any{"error": business.Error()})
			return string(encoded), nil
		}
		return "", err
	}
	encoded, err := json.Marshal(result)
	return string(encoded), err
}

func (a *Activities) BookFlight(ctx context.Context, req CheckoutStepRequest) (CheckoutReservation, error) {
	return a.reserve(ctx, req)
}

func (a *Activities) BookHotel(ctx context.Context, req CheckoutStepRequest) (CheckoutReservation, error) {
	if a.cfg.CheckoutStepDelay > 0 {
		time.Sleep(a.cfg.CheckoutStepDelay)
	}
	if a.cfg.CheckoutFailHotel {
		return CheckoutReservation{}, temporal.NewNonRetryableApplicationError("Hotel booking failed — the supplier returned no availability (injected demo failure).", "HotelBookingFailed", nil)
	}
	return reservation(req), nil
}

func (a *Activities) BookActivity(ctx context.Context, req CheckoutStepRequest) (CheckoutReservation, error) {
	return a.reserve(ctx, req)
}

func (a *Activities) reserve(_ context.Context, req CheckoutStepRequest) (CheckoutReservation, error) {
	if a.cfg.CheckoutStepDelay > 0 {
		time.Sleep(a.cfg.CheckoutStepDelay)
	}
	return reservation(req), nil
}

func reservation(req CheckoutStepRequest) CheckoutReservation {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s:%s:%d", req.AccountKey, req.Item.Kind, req.Item.RefID)))
	prefix := map[string]string{"flight": "FLT", "hotel": "HTL", "activity": "ACT"}[req.Item.Kind]
	return CheckoutReservation{Kind: req.Item.Kind, RefID: req.Item.RefID, Title: req.Item.Title, ReservationID: prefix + "-" + strings.ToUpper(hex.EncodeToString(digest[:])[:10]), Status: "booked"}
}

func (a *Activities) CancelFlight(ctx context.Context, res CheckoutReservation) (CheckoutReservation, error) {
	return a.cancel(ctx, res)
}
func (a *Activities) CancelHotel(ctx context.Context, res CheckoutReservation) (CheckoutReservation, error) {
	return a.cancel(ctx, res)
}
func (a *Activities) CancelActivity(ctx context.Context, res CheckoutReservation) (CheckoutReservation, error) {
	return a.cancel(ctx, res)
}
func (a *Activities) cancel(_ context.Context, res CheckoutReservation) (CheckoutReservation, error) {
	if a.cfg.CheckoutStepDelay > 0 {
		time.Sleep(a.cfg.CheckoutStepDelay)
	}
	res.Status = "cancelled"
	return res, nil
}

func (a *Activities) FinalizeCheckout(ctx context.Context, req CheckoutRequest) (FinalizeCheckoutResult, error) {
	already, err := a.db.ItemsAlreadyBooked(ctx, req.AccountKey, req.Items)
	if err != nil {
		return FinalizeCheckoutResult{}, err
	}
	if len(already) > 0 {
		names := make([]string, 0, len(already))
		for _, item := range already {
			names = append(names, fmt.Sprintf("%q", stringValue(item["title"])))
		}
		return FinalizeCheckoutResult{}, temporal.NewNonRetryableApplicationError("Booking declined — this trip already includes "+strings.Join(names, ", ")+".", "BookingDeclined", nil)
	}
	booking, err := a.db.RecordBooking(ctx, req.AccountKey, req.Items, req.Summary)
	if err != nil {
		return FinalizeCheckoutResult{}, err
	}
	return FinalizeCheckoutResult{BookingID: int64Value(booking["booking_id"])}, nil
}

func sliceValue(value any) []any {
	if result, ok := value.([]any); ok {
		return result
	}
	return nil
}

func mapSlice(value any) []map[string]any {
	values := sliceValue(value)
	result := make([]map[string]any, 0, len(values))
	for _, value := range values {
		if m, ok := value.(map[string]any); ok {
			result = append(result, m)
		}
	}
	return result
}
