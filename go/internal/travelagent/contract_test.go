package travelagent

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
)

func TestGatewayDTOsUseSnakeCase(t *testing.T) {
	raw, err := json.Marshal(ResearchStatus{Phase: "searching", Plan: []SearchItem{}, SearchesTotal: 3, SearchesDone: 2})
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"phase", "plan", "searches_total", "searches_done"} {
		if _, ok := decoded[key]; !ok {
			t.Fatalf("missing gateway key %q in %s", key, raw)
		}
	}
}

func TestToolCatalogMatchesContract(t *testing.T) {
	want := map[string]bool{
		"search_events": true, "search_destinations": true, "get_destination_info": true,
		"search_flights": true, "search_hotels": true, "search_attractions": true,
		"research_destination": true, "create_invoice": true, "add_to_itinerary": true,
		"remove_from_itinerary": true, "book_trip": true, "get_bookings": true,
		"get_booking_details": true,
	}
	for _, tool := range Tools {
		delete(want, tool.Name)
	}
	if len(want) != 0 {
		t.Fatalf("missing tools: %v", want)
	}
}

func TestTravelAgentWorkflowRegistersGatewayQueries(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var queryErr error
	env.RegisterDelayedCallback(func() {
		queries := []struct {
			name   string
			result any
		}{
			{"is_llm_down", new(bool)},
			{"transcript", new([]ChatMessage)},
			{"pending_approval", new(*PendingConfirmation)},
			{"research_status", new(ResearchStatus)},
			{"itinerary_view", new([]ItineraryItem)},
		}
		for _, query := range queries {
			value, err := env.QueryWorkflow(query.name)
			if err == nil {
				err = value.Get(query.result)
			}
			if err != nil {
				queryErr = fmt.Errorf("query %s: %w", query.name, err)
				break
			}
		}
		env.CancelWorkflow()
	}, time.Second)

	env.ExecuteWorkflow(TravelAgentWorkflow, "traveller@example.com")
	if queryErr != nil {
		t.Fatal(queryErr)
	}
	if err := env.GetWorkflowError(); !temporal.IsCanceledError(err) {
		t.Fatalf("workflow should reach its wait state and then be cancelled, got %v", err)
	}
}

func TestCheckoutSimulatesHotelFailureOnlyOnFirstSessionAttempt(t *testing.T) {
	firstRequest := checkoutRequestForAttempt("trip-test", checkoutTestItems(), "2 item(s) — $300.00", 1)
	secondRequest := checkoutRequestForAttempt("trip-test", checkoutTestItems(), "2 item(s) — $300.00", 2)
	if !firstRequest.SimulateHotelFailure || secondRequest.SimulateHotelFailure {
		t.Fatal("only checkout attempt 1 should request the simulated hotel failure")
	}

	first := executeCheckoutAttempt(t, "trip-test-checkout-1", firstRequest)
	if first.Status != "compensated" {
		t.Fatalf("first checkout should exercise compensation, got %q", first.Status)
	}
	second := executeCheckoutAttempt(t, "trip-test-checkout-2", secondRequest)
	if second.Status != "booked" {
		t.Fatalf("second checkout should succeed, got %q", second.Status)
	}
}

func checkoutTestItems() []ItineraryItem {
	return []ItineraryItem{
		{Kind: "flight", RefID: 1, Title: "Test Flight", Price: 100},
		{Kind: "hotel", RefID: 2, Title: "Test Hotel", Price: 200},
	}
}

func executeCheckoutAttempt(t *testing.T, workflowID string, request CheckoutRequest) CheckoutResult {
	t.Helper()
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	env.SetStartWorkflowOptions(client.StartWorkflowOptions{ID: workflowID})
	activities := &Activities{cfg: Config{CheckoutFailHotel: true}}
	env.RegisterActivityWithOptions(activities.BookFlight, activity.RegisterOptions{Name: "book_flight"})
	env.RegisterActivityWithOptions(activities.BookHotel, activity.RegisterOptions{Name: "book_hotel"})
	env.RegisterActivityWithOptions(activities.CancelFlight, activity.RegisterOptions{Name: "cancel_flight"})
	env.RegisterActivityWithOptions(
		func(context.Context, CheckoutRequest) (FinalizeCheckoutResult, error) {
			return FinalizeCheckoutResult{BookingID: 1}, nil
		},
		activity.RegisterOptions{Name: "finalize_checkout"},
	)

	env.ExecuteWorkflow(CheckoutWorkflow, request)
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("checkout workflow failed: %v", err)
	}
	var result CheckoutResult
	if err := env.GetWorkflowResult(&result); err != nil {
		t.Fatalf("read checkout result: %v", err)
	}
	return result
}
