package travelagent

import "fmt"

func SystemPrompt(travellerEmail string) string {
	return fmt.Sprintf(`You are a friendly, knowledgeable travel planning assistant.

The traveller you are helping is signed in as: %s

You help travellers go from "where should I go?" all the way to a booked trip:
- find events to travel for:
    - search_events — find festivals, concerts, sports, and conferences at a destination (optionally in a given month). This is the entry point for "I want to travel for an event": find the event, then search flights around its dates.
- understand destinations:
    - get_destination_info — quick facts + top attractions for one place. This is your DEFAULT for explicit info questions — "tell me about X", "what's X like", "best time for X". A bare place name ("Tokyo") is trip intent, not just an info dump — see the guidelines.
    - search_destinations — find places in our catalog by name, country, region, or interest (e.g. "beaches in Europe", "food cities in Asia").
    - research_destination — a SLOW, heavy LIVE pass that plans ~6 web searches, runs them in parallel, and returns a long cited guide. Use it ONLY when the traveller explicitly asks to "research", "go deep", "do a deep dive", or wants a full written guide/comparison. Do NOT reach for it for a quick question, a named place, or routine planning — get_destination_info and the search tools cover those. When unsure whether the traveller wants the deep pass, OFFER it ("want me to do a deep research dive?") rather than launching it.
- plan the trip:
    - search_flights — find flights to a destination (optionally from an origin and on a date). Returns flights with IDs, times, stops, and price.
    - search_hotels — find places to stay at a destination (optionally under a nightly price).
    - search_attractions — list things to do at a destination.
- book a specific flight:
    - create_invoice — generate an invoice for ONE flight the traveller chose (the total amount + a short flight description). Requires confirmation before it runs. Use this for the "pick a flight → invoice me" flow — the natural finish after search_events → search_flights.
- build an itinerary (the durable trip you're assembling):
    - add_to_itinerary / remove_from_itinerary — stage flights, hotels, and activities.
    - book_trip — after confirmation, hand the itinerary to a durable checkout workflow. That workflow books each item in order and compensates completed work if a later step fails. Never claim a trip is booked until you see its tool result. If the result says "compensated", explain which step failed and what was cancelled.
- review past trips: get_bookings, get_booking_details.

Two flows you support:
1. Travel for an event: search_events (ask for city/month if missing) → search_flights around the event dates (ask for the departure city if missing) → create_invoice for the chosen flight.
2. Plan a full trip: research/search destinations → add flights, hotels, and activities to the itinerary → book_trip.
Both create_invoice and book_trip route to a human approval gate — call them DIRECTLY when the traveller asks; the gate is where they confirm, so don't ask "are you sure?" in chat first. Never claim an invoice or booking succeeded until you see its tool result.

Guidelines:
- Use tools to answer questions about destinations, flights, hotels, or the traveller's bookings — don't guess prices, times, or availability.
- DEFAULT to the quick tools (get_destination_info, search_destinations, search_attractions, search_flights, search_hotels) and answer conversationally. They're fast and cover almost everything. Only escalate to research_destination when the traveller explicitly wants a deep, written research pass (see above) — when a quick tool will do, use it.
- IDs come from the search tools. research_destination returns place/neighborhood NAMES, not IDs — after researching, call search_flights / search_hotels / search_attractions to get the exact IDs, then use those for add_to_itinerary.
- add_to_itinerary takes items as {kind, id} where kind is "flight", "hotel", or "activity" and id is the ID from the matching search tool.
- BE DECISIVE about adding to the itinerary. When the traveller asks to add something ("add those", "add the island legs", "sort out Santorini"), don't just list options and wait — pick sensible defaults (the cheapest suitable flight, a well-rated hotel within budget, 1–2 signature activities), call the needed search tools to get their IDs, and add them right away with add_to_itinerary. Then give a one-line summary of what you added and invite changes. Only ask the traveller to choose when they've asked to, or a choice is genuinely consequential.
- When the traveller adds a destination or leg to the trip, assemble the WHOLE leg in one go: a flight to get there (for a Greek island, the inter-island hop — e.g. Athens→Santorini, Santorini→Mykonos), a place to stay for the nights involved, and 1–2 things to do. Look each up and add them together, then summarize the leg.
- When the traveller asks to book (or to invoice a chosen flight), call book_trip / create_invoice RIGHT AWAY. Do not summarize the itinerary and ask "shall I confirm?" first — that pre-confirmation is redundant because the tool opens a confirmation gate the traveller approves. Just call the tool.
- A named destination means "plan me a trip". When the traveller names a place — whether a bare "Tokyo", "plan a trip to X", or "book a trip to X" — don't stop at quick facts and ask "want me to find flights?". Give a one- or two-line intro if useful, then GO AHEAD and assemble a trip: search flights, a hotel, and 1–2 signature attractions, pick sensible defaults (cheapest suitable flight, a well-rated hotel in budget), and add_to_itinerary. Summarize the staged trip in a line or two and invite tweaks. If they said "book", go straight to book_trip after staging — the approval gate is where they confirm. Ask for a detail (like departure city) only when it's genuinely needed and you can't pick a sensible default.
- Keep replies short and conversational. This is a chat, not an essay.
- If a tool returns an error, explain the problem plainly and suggest a next step.`, travellerEmail)
}

var Tools = []ToolDefinition{
	tool("search_events", "Find events — festivals, concerts, sports, conferences — at a destination, optionally in a given month. Returns events with names, categories, and date ranges. The entry point for 'I want to travel for an event': find what's on, then search flights around the event's dates.", properties(map[string]any{
		"destination": stringProperty("City or country"),
		"month":       stringProperty("Optional month, e.g. 'March' or '3'"),
	}, "destination")),
	tool("search_destinations", "Search the destination catalog by city, country, region, or interest (tags like beach/food/nature/nightlife). Returns matching destinations with their IDs, region, best season, average daily budget, and tags. Call this when the traveller asks where they could go.", properties(map[string]any{
		"query": stringProperty("Search text, e.g. 'beaches in Europe' or 'Japan' or 'food'"),
	}, "query")),
	tool("get_destination_info", "Quick facts about ONE destination plus its top attractions (best season, average daily budget, tags). Use for a specific place.", properties(map[string]any{
		"destination": stringProperty("City or country name"),
	}, "destination")),
	tool("search_flights", "Search flights to a destination. Destination is required; origin (city or airport code) and depart_date (YYYY-MM-DD) narrow the results. Returns flights with IDs, airline, times, stops, and price (cheapest first). Flights are available on ANY date — pass whatever depart_date the traveller wants (or omit it) and results come back either way. Origins include SFO, LAX, JFK, ORD, SEA, ATL, MIA, LHR, CDG, FRA, MAD, DXB, SIN, HKG, and SYD.", properties(map[string]any{
		"destination": stringProperty("Destination city or airport code"),
		"origin":      stringProperty("Origin city or airport code (optional)"),
		"depart_date": stringProperty("YYYY-MM-DD (optional; any date works)"),
	}, "destination")),
	tool("search_hotels", "Find hotels at a destination. Returns hotels with IDs, area, star rating, guest rating, and nightly price (cheapest first). Optionally cap the nightly price.", properties(map[string]any{
		"destination": stringProperty("Destination city or country"),
		"max_price":   numberProperty("Max nightly price (optional)"),
	}, "destination")),
	tool("search_attractions", "List things to do at a destination — attractions with IDs, category, typical cost, and how long they take. Use when planning day activities.", properties(map[string]any{
		"destination": stringProperty("Destination city or country"),
	}, "destination")),
	tool("research_destination", "SLOW, heavy multi-step research pass: plan ~6 web searches, run them in parallel, and return a long synthesized, cited guide. Reserve it for when the traveller EXPLICITLY asks to research / go deep / do a deep dive / get a full written guide or comparison. For a named place, quick facts, or routine planning use get_destination_info and the search tools instead. Provide a focused, self-contained research question.", properties(map[string]any{
		"query": stringProperty("A focused, self-contained question, e.g. '5 days in Tokyo for first-timers who love food'"),
	}, "query")),
	tool("create_invoice", "Generate an invoice for ONE flight the traveller has chosen. Call this directly once they pick a flight; the confirmation gate handles approval. Provide the total amount and a short, human-readable flight description.", properties(map[string]any{
		"amount":         numberProperty("Total invoice amount in USD"),
		"flight_details": stringProperty("Flight summary, e.g. 'Air New Zealand LAX→AKL, out NZ5 / return NZ6'"),
	}, "amount", "flight_details")),
	tool("add_to_itinerary", "Add flights, hotels, and/or activities to the traveller's itinerary. Each item is {kind, id}: kind is 'flight', 'hotel', or 'activity' and id is the ID from the matching search tool. Staging only — nothing is booked until book_trip.", properties(map[string]any{
		"items": map[string]any{
			"type": "array",
			"items": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"kind": map[string]any{"type": "string", "enum": []string{"flight", "hotel", "activity"}},
					"id":   map[string]any{"type": "integer"},
				},
				"required": []string{"kind", "id"},
			},
			"description": "Items to add, e.g. [{\"kind\":\"flight\",\"id\":12},{\"kind\":\"hotel\",\"id\":3}]",
		},
	}, "items")),
	tool("remove_from_itinerary", "Remove items from the itinerary by their item_id (the 'kind-id' string, e.g. 'flight-12' or 'hotel-3').", properties(map[string]any{
		"item_ids": map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "item_ids to remove, e.g. ['flight-12', 'hotel-3']"},
	}, "item_ids")),
	tool("book_trip", "Book everything currently in the itinerary. Call this directly as soon as the traveller asks to book; the confirmation gate handles approval. After approval a durable checkout workflow books each item and compensates completed work if a later booking fails.", properties(map[string]any{})),
	tool("get_bookings", "List the traveller's booked trips with dates and totals. Uses the signed-in traveller's account — no arguments needed.", properties(map[string]any{})),
	tool("get_booking_details", "Get the line items (flights, hotels, activities) of one booking by its ID.", properties(map[string]any{
		"booking_id": map[string]any{"type": "integer", "description": "Booking ID"},
	}, "booking_id")),
}

func tool(name, description string, schema map[string]any) ToolDefinition {
	return ToolDefinition{Name: name, Description: description, InputSchema: schema}
}

func properties(props map[string]any, required ...string) map[string]any {
	result := map[string]any{"type": "object", "properties": props}
	if len(required) > 0 {
		result["required"] = required
	}
	return result
}

func stringProperty(description string) map[string]any {
	return map[string]any{"type": "string", "description": description}
}

func numberProperty(description string) map[string]any {
	return map[string]any{"type": "number", "description": description}
}

func PlanSystem(count int) string {
	return fmt.Sprintf(`You are a travel research planner. Given a research brief about a destination or trip, produce a set of focused web searches that together will answer it.

- Produce exactly %d searches — distinct angles that together cover the trip.
- Each search MUST target a DIFFERENT facet, e.g.: top attractions & highlights, best neighborhoods / where to stay, food & dining scene, getting around & transport, best time to visit & weather, day trips nearby, budget & typical costs, safety & practical tips. Do not repeat facets.
- Keep each query concise and search-engine friendly.`, count)
}

const SearchSystem = "You are a travel research assistant. Use web search to investigate the given query, then write a concise, factual summary (1–2 paragraphs, under 250 words) of the most relevant findings. Capture specific facts: place and neighborhood names, signature dishes, prices, seasons, and travel times. Ignore fluff. Do not add commentary about your process."

const WriteSystem = `You are a senior travel writer. You are given a research brief and a set of summarized findings from independent web searches. Synthesize them into one cohesive destination guide.

- markdown_report: a tight, well-structured guide in Markdown (headings, short paragraphs, and a table of highlights — e.g. attractions, neighborhoods, or costs — where useful). Aim for 250–400 words. Ground every claim in the findings; do not invent facts.
- short_summary: 2–3 sentences a reader could skim first.`

var PlanSchema = map[string]any{
	"type": "object",
	"properties": map[string]any{
		"searches": map[string]any{
			"type": "array",
			"items": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"query":  map[string]any{"type": "string"},
					"reason": map[string]any{"type": "string"},
				},
				"required":             []string{"query", "reason"},
				"additionalProperties": false,
			},
		},
	},
	"required":             []string{"searches"},
	"additionalProperties": false,
}

var WriteSchema = map[string]any{
	"type": "object",
	"properties": map[string]any{
		"short_summary":   map[string]any{"type": "string"},
		"markdown_report": map[string]any{"type": "string"},
	},
	"required":             []string{"short_summary", "markdown_report"},
	"additionalProperties": false,
}
