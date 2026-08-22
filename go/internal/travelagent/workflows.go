package travelagent

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

type agentState struct {
	messages            []ChatMessage
	accountKey          string
	pendingConfirmation *PendingConfirmation
	approval            *ApprovalDecision
	turnInProgress      bool
	llmDown             bool
	checkoutAttempt     int
	itinerary           []ItineraryItem
	phase               string
	plan                []SearchItem
	searchesTotal       int
	searchesDone        int
}

type toolOutcome struct {
	Result        string
	Terminal      bool
	AssistantText string
}

// TravelAgentWorkflow is registered under this exact name for compatibility
// with the shared Python gateway. It remains open for the conversation lifetime.
func TravelAgentWorkflow(ctx workflow.Context, travellerEmail string) error {
	s := &agentState{
		messages:   []ChatMessage{{Role: "system", Content: SystemPrompt(travellerEmail)}},
		accountKey: workflow.GetInfo(ctx).WorkflowExecution.ID,
		itinerary:  []ItineraryItem{}, phase: "idle", plan: []SearchItem{},
	}

	if err := installHandlers(ctx, s); err != nil {
		return err
	}

	for {
		if err := workflow.Await(ctx, func() bool { return s.turnInProgress }); err != nil {
			return err
		}
		for {
			response := LLMResponse{}
			err := workflow.ExecuteActivity(llmContext(ctx), "call_llm", LLMRequest{Messages: s.messages}).Get(ctx, &response)
			if err != nil {
				response.Message = ChatMessage{Role: "assistant", Content: "I'm sorry — I hit an error I couldn't recover from. Please try again in a moment."}
			}
			s.messages = append(s.messages, response.Message)
			if len(response.Message.ToolCalls) == 0 {
				break
			}
			finalAnswer := ""
			terminal := false
			for _, call := range response.Message.ToolCalls {
				outcome := dispatchTool(ctx, s, call)
				id := call.ID
				s.messages = append(s.messages, ChatMessage{Role: "tool", Content: outcome.Result, ToolCallID: &id})
				if outcome.Terminal {
					terminal, finalAnswer = true, outcome.AssistantText
				}
			}
			if terminal {
				s.messages = append(s.messages, ChatMessage{Role: "assistant", Content: finalAnswer})
				break
			}
		}
		s.phase = "idle"
		s.turnInProgress = false
	}
}

func installHandlers(ctx workflow.Context, s *agentState) error {
	if err := workflow.SetUpdateHandler(ctx, "send_message", func(ctx workflow.Context, text string) (TurnResult, error) {
		if s.turnInProgress {
			return TurnResult{}, temporal.NewNonRetryableApplicationError("A turn is already in progress.", "TurnInProgress", nil)
		}
		start := len(s.messages)
		s.messages = append(s.messages, ChatMessage{Role: "user", Content: text})
		s.turnInProgress = true
		if err := workflow.Await(ctx, func() bool { return !s.turnInProgress || s.pendingConfirmation != nil }); err != nil {
			return TurnResult{}, err
		}
		reply := lastAssistant(s.messages, start)
		if s.pendingConfirmation != nil {
			return TurnResult{Status: "awaiting_approval", Reply: reply}, nil
		}
		return TurnResult{Status: "reply", Reply: reply}, nil
	}); err != nil {
		return err
	}

	confirm := workflow.GetSignalChannel(ctx, "confirm_action")
	workflow.Go(ctx, func(ctx workflow.Context) {
		for {
			var decision ApprovalDecision
			confirm.Receive(ctx, &decision)
			s.approval = &decision
		}
	})
	llmStatus := workflow.GetSignalChannel(ctx, "set_llm_status")
	workflow.Go(ctx, func(ctx workflow.Context) {
		for {
			llmStatus.Receive(ctx, &s.llmDown)
		}
	})

	queries := []struct {
		name    string
		handler any
	}{
		{"is_llm_down", func() (bool, error) { return s.llmDown, nil }},
		{"transcript", func() ([]ChatMessage, error) {
			out := []ChatMessage{}
			for _, message := range s.messages {
				if (message.Role == "user" || message.Role == "assistant") && message.Content != "" {
					out = append(out, message)
				}
			}
			return out, nil
		}},
		{"pending_approval", func() (*PendingConfirmation, error) { return s.pendingConfirmation, nil }},
		{"research_status", func() (ResearchStatus, error) {
			return ResearchStatus{Phase: s.phase, Plan: s.plan, SearchesTotal: s.searchesTotal, SearchesDone: s.searchesDone}, nil
		}},
		{"itinerary_view", func() ([]ItineraryItem, error) { return s.itinerary, nil }},
	}
	for _, query := range queries {
		if err := workflow.SetQueryHandler(ctx, query.name, query.handler); err != nil {
			return err
		}
	}
	return nil
}

func dispatchTool(ctx workflow.Context, s *agentState, call ToolCall) toolOutcome {
	var outcome toolOutcome
	var err error
	switch call.Name {
	case "research_destination":
		outcome, err = research(ctx, s, stringValue(call.Args["query"]))
	case "add_to_itinerary":
		outcome, err = addToItinerary(ctx, s, call)
	case "remove_from_itinerary":
		outcome = removeFromItinerary(s, call)
	case "book_trip":
		outcome, err = bookTrip(ctx, s)
	case "create_invoice":
		outcome, err = createInvoice(ctx, s, call)
	default:
		outcome.Result, err = runTool(ctx, s.accountKey, call)
	}
	if err != nil {
		return toolOutcome{Result: jsonString(map[string]any{"error": failureMessage(err)})}
	}
	return outcome
}

func runTool(ctx workflow.Context, accountKey string, call ToolCall) (string, error) {
	activityCtx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Second,
		RetryPolicy:         &temporal.RetryPolicy{InitialInterval: time.Second, BackoffCoefficient: 2, MaximumInterval: 10 * time.Second, NonRetryableErrorTypes: []string{"BookingDeclined"}},
		Summary:             call.Name,
	})
	var result string
	err := workflow.ExecuteActivity(activityCtx, "execute_tool", ToolRequest{Call: call, AccountKey: accountKey}).Get(ctx, &result)
	return result, err
}

func research(ctx workflow.Context, s *agentState, query string) (toolOutcome, error) {
	s.plan, s.searchesTotal, s.searchesDone = []SearchItem{}, 0, 0
	s.phase = "planning"
	var plan SearchPlan
	if err := workflow.ExecuteActivity(researchContext(ctx, 90*time.Second), "plan_searches", query).Get(ctx, &plan); err != nil {
		return toolOutcome{}, err
	}
	s.plan, s.searchesTotal, s.phase = plan.Searches, len(plan.Searches), "searching"
	type searchResult struct {
		Index int
		Text  string
		Err   error
	}
	results := workflow.NewChannel(ctx)
	for i, item := range plan.Searches {
		i, item := i, item
		workflow.Go(ctx, func(ctx workflow.Context) {
			var text string
			err := workflow.ExecuteActivity(researchContext(ctx, 120*time.Second), "web_search", item).Get(ctx, &text)
			results.Send(ctx, searchResult{Index: i, Text: text, Err: err})
		})
	}
	findings := make([]string, len(plan.Searches))
	for range plan.Searches {
		var result searchResult
		results.Receive(ctx, &result)
		if result.Err != nil {
			return toolOutcome{}, result.Err
		}
		findings[result.Index] = result.Text
		s.searchesDone++
	}
	s.phase = "writing"
	var report ReportData
	if err := workflow.ExecuteActivity(researchContext(ctx, 180*time.Second), "write_report", WriteRequest{Brief: query, Findings: findings}).Get(ctx, &report); err != nil {
		return toolOutcome{}, err
	}
	s.phase = "idle"
	return toolOutcome{Result: report.ShortSummary + "\n\n" + report.MarkdownReport, Terminal: true, AssistantText: report.MarkdownReport}, nil
}

func addToItinerary(ctx workflow.Context, s *agentState, call ToolCall) (toolOutcome, error) {
	result, err := runTool(ctx, s.accountKey, call)
	if err != nil {
		return toolOutcome{}, err
	}
	var items []ItineraryItem
	if err := json.Unmarshal([]byte(result), &items); err != nil {
		return toolOutcome{Result: result}, nil
	}
	existing := map[string]bool{}
	for _, item := range s.itinerary {
		existing[itemID(item)] = true
	}
	added := []map[string]any{}
	for _, item := range items {
		if existing[itemID(item)] {
			continue
		}
		s.itinerary = append(s.itinerary, item)
		existing[itemID(item)] = true
		added = append(added, map[string]any{"item_id": itemID(item), "title": item.Title})
	}
	return toolOutcome{Result: jsonString(map[string]any{"added": added, "itinerary_size": len(s.itinerary), "itinerary_total": itineraryTotal(s.itinerary)})}, nil
}

func removeFromItinerary(s *agentState, call ToolCall) toolOutcome {
	ids := map[string]bool{}
	for _, id := range sliceValue(call.Args["item_ids"]) {
		ids[stringValue(id)] = true
	}
	before := len(s.itinerary)
	kept := make([]ItineraryItem, 0, before)
	for _, item := range s.itinerary {
		if !ids[itemID(item)] {
			kept = append(kept, item)
		}
	}
	s.itinerary = kept
	return toolOutcome{Result: jsonString(map[string]any{"removed": before - len(kept), "itinerary_size": len(kept), "itinerary_total": itineraryTotal(kept)})}
}

func awaitApproval(ctx workflow.Context, s *agentState) (ApprovalDecision, error) {
	if err := workflow.Await(ctx, func() bool { return s.approval != nil }); err != nil {
		return ApprovalDecision{}, err
	}
	decision := *s.approval
	s.approval, s.pendingConfirmation = nil, nil
	return decision, nil
}

func bookTrip(ctx workflow.Context, s *agentState) (toolOutcome, error) {
	if len(s.itinerary) == 0 {
		return toolOutcome{Result: jsonString(map[string]any{"error": "The itinerary is empty — add flights, hotels, or activities before booking."})}, nil
	}
	total := itineraryTotal(s.itinerary)
	summary := fmt.Sprintf("%d item(s) — $%.2f", len(s.itinerary), total)
	args := make([]map[string]any, 0, len(s.itinerary))
	for _, item := range s.itinerary {
		args = append(args, map[string]any{"title": item.Title, "price": item.Price})
	}
	s.pendingConfirmation = &PendingConfirmation{Action: "book_trip", Title: "Booking approval required", Detail: summary, Amount: total, Args: map[string]any{"items": args}}
	decision, err := awaitApproval(ctx, s)
	if err != nil {
		return toolOutcome{}, err
	}
	if !decision.Approved {
		reason := ""
		if decision.Reason != nil {
			reason = " Reason: " + *decision.Reason
		}
		return toolOutcome{Result: "The traveller DECLINED this booking." + reason}, nil
	}
	s.checkoutAttempt++
	childCtx := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: fmt.Sprintf("%s-checkout-%d", s.accountKey, s.checkoutAttempt)})
	var checkout CheckoutResult
	err = workflow.ExecuteChildWorkflow(childCtx, "CheckoutWorkflow", CheckoutRequest{AccountKey: s.accountKey, Items: append([]ItineraryItem(nil), s.itinerary...), Summary: summary}).Get(ctx, &checkout)
	if err != nil {
		return toolOutcome{}, err
	}
	if checkout.Status == "booked" {
		s.itinerary = []ItineraryItem{}
	}
	return toolOutcome{Result: jsonString(checkout)}, nil
}

func createInvoice(ctx workflow.Context, s *agentState, call ToolCall) (toolOutcome, error) {
	amount := round2(floatValue(call.Args["amount"]))
	details := stringValue(call.Args["flight_details"])
	if amount <= 0 || details == "" {
		return toolOutcome{Result: jsonString(map[string]any{"error": "Need a positive amount and a flight description to create an invoice."})}, nil
	}
	s.pendingConfirmation = &PendingConfirmation{Action: "create_invoice", Title: "Create invoice", Detail: details, Amount: amount, Args: map[string]any{"amount": amount, "flight_details": details}}
	decision, err := awaitApproval(ctx, s)
	if err != nil {
		return toolOutcome{}, err
	}
	if !decision.Approved {
		reason := ""
		if decision.Reason != nil {
			reason = " Reason: " + *decision.Reason
		}
		return toolOutcome{Result: "The traveller DECLINED the invoice." + reason}, nil
	}
	result, err := runTool(ctx, s.accountKey, ToolCall{ID: "invoice", Name: "create_invoice", Args: map[string]any{"amount": amount, "flight_details": details}})
	return toolOutcome{Result: result}, err
}

// CheckoutWorkflow makes the booking order and reverse compensation explicit.
func CheckoutWorkflow(ctx workflow.Context, req CheckoutRequest) (CheckoutResult, error) {
	options := workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Second,
		RetryPolicy:         &temporal.RetryPolicy{InitialInterval: time.Second, BackoffCoefficient: 2, MaximumInterval: 5 * time.Second, MaximumAttempts: 3, NonRetryableErrorTypes: []string{"HotelBookingFailed", "BookingDeclined"}},
	}
	ctx = workflow.WithActivityOptions(ctx, options)
	reservations := []CheckoutReservation{}
	activityByKind := map[string]string{"flight": "book_flight", "hotel": "book_hotel", "activity": "book_activity"}
	for _, kind := range []string{"flight", "hotel", "activity"} {
		for _, item := range req.Items {
			if item.Kind != kind {
				continue
			}
			var reservation CheckoutReservation
			err := workflow.ExecuteActivity(ctx, activityByKind[kind], CheckoutStepRequest{AccountKey: req.AccountKey, Item: item}).Get(ctx, &reservation)
			if err != nil {
				return compensateCheckout(ctx, req, reservations, err), nil
			}
			reservations = append(reservations, reservation)
		}
	}
	var finalized FinalizeCheckoutResult
	if err := workflow.ExecuteActivity(ctx, "finalize_checkout", req).Get(ctx, &finalized); err != nil {
		return compensateCheckout(ctx, req, reservations, err), nil
	}
	bookingID := finalized.BookingID
	return CheckoutResult{Status: "booked", Message: "Checkout completed and every itinerary item is booked.", WorkflowID: workflow.GetInfo(ctx).WorkflowExecution.ID, Reservations: reservations, Compensations: []CheckoutReservation{}, BookingID: &bookingID}, nil
}

func compensateCheckout(ctx workflow.Context, _ CheckoutRequest, reservations []CheckoutReservation, cause error) CheckoutResult {
	compensations := []CheckoutReservation{}
	cancelByKind := map[string]string{"flight": "cancel_flight", "hotel": "cancel_hotel", "activity": "cancel_activity"}
	for i := len(reservations) - 1; i >= 0; i-- {
		var cancelled CheckoutReservation
		if workflow.ExecuteActivity(ctx, cancelByKind[reservations[i].Kind], reservations[i]).Get(ctx, &cancelled) == nil {
			compensations = append(compensations, cancelled)
		}
	}
	names := []string{}
	for _, item := range compensations {
		names = append(names, item.Title)
	}
	if len(names) == 0 {
		names = []string{"no prior reservations"}
	}
	failure := failureMessage(cause)
	return CheckoutResult{Status: "compensated", Message: "Checkout stopped: " + failure + " Compensation completed: cancelled " + strings.Join(names, ", ") + ".", WorkflowID: workflow.GetInfo(ctx).WorkflowExecution.ID, Reservations: reservations, Compensations: compensations, Failure: &failure}
}

func llmContext(ctx workflow.Context) workflow.Context {
	return workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 60 * time.Second, RetryPolicy: llmRetry()})
}
func researchContext(ctx workflow.Context, timeout time.Duration) workflow.Context {
	return workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: timeout, RetryPolicy: llmRetry()})
}
func llmRetry() *temporal.RetryPolicy {
	return &temporal.RetryPolicy{InitialInterval: time.Second, BackoffCoefficient: 2, MaximumInterval: 10 * time.Second, NonRetryableErrorTypes: []string{"LLMFatalError"}}
}
func itemID(item ItineraryItem) string { return fmt.Sprintf("%s-%d", item.Kind, item.RefID) }
func itineraryTotal(items []ItineraryItem) float64 {
	total := 0.0
	for _, item := range items {
		total += item.Price
	}
	return round2(total)
}
func lastAssistant(messages []ChatMessage, since int) string {
	for i := len(messages) - 1; i >= since; i-- {
		if messages[i].Role == "assistant" && messages[i].Content != "" {
			return messages[i].Content
		}
	}
	return ""
}
func failureMessage(err error) string {
	if err == nil {
		return "That action could not be completed."
	}
	return err.Error()
}
func jsonString(value any) string {
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
