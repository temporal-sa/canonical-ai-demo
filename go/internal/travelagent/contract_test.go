package travelagent

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

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
