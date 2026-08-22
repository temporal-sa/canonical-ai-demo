package travelagent

import (
	"encoding/json"
	"testing"
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
