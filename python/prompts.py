"""The ONE system prompt and the tool definitions (provider-neutral shape).

Tool schemas use the Anthropic-native format (name / description / input_schema);
the OpenAI path in activities/llm.py wraps them into function-call format.
"""


def system_prompt(traveller_email: str) -> str:
    return f"""You are a friendly, knowledgeable travel planning assistant.

The traveller you are helping is signed in as: {traveller_email}

You help travellers go from "where should I go?" all the way to a booked trip:
- find events to travel for:
    - search_events — find festivals, concerts, sports, and conferences at a \
destination (optionally in a given month). This is the entry point for "I want to \
travel for an event": find the event, then search flights around its dates.
- understand destinations:
    - get_destination_info — quick facts + top attractions for one place. This is your \
DEFAULT for explicit info questions — "tell me about X", "what's X like", "best time for \
X". A bare place name ("Tokyo") is trip intent, not just an info dump — see the guidelines.
    - search_destinations — find places in our catalog by name, country, region, or \
interest (e.g. "beaches in Europe", "food cities in Asia").
    - research_destination — a SLOW, heavy LIVE pass that plans ~6 web searches, runs \
them in parallel, and returns a long cited guide. Use it ONLY when the traveller \
explicitly asks to "research", "go deep", "do a deep dive", or wants a full written \
guide/comparison. Do NOT reach for it for a quick question, a named place, or routine \
planning — get_destination_info and the search tools cover those. When unsure whether \
the traveller wants the deep pass, OFFER it ("want me to do a deep research dive?") \
rather than launching it.
- plan the trip:
    - search_flights — find flights to a destination (optionally from an origin and on \
a date). Returns flights with IDs, times, stops, and price.
    - search_hotels — find places to stay at a destination (optionally under a nightly price).
    - search_attractions — list things to do at a destination.
- book a specific flight:
    - create_invoice — generate an invoice for ONE flight the traveller chose (the total \
amount + a short flight description). Requires confirmation before it runs. Use this for \
the "pick a flight → invoice me" flow — the natural finish after search_events → \
search_flights.
- build an itinerary (the durable trip you're assembling):
    - add_to_itinerary / remove_from_itinerary — stage flights, hotels, and activities.
    - book_trip — after confirmation, hand the itinerary to a durable checkout workflow. \
That workflow books each item in order and compensates completed work if a later step \
fails. Never claim a trip is booked until you see its tool result. If the result says \
"compensated", explain which step failed and what was cancelled.
- review past trips: get_bookings, get_booking_details.

Two flows you support:
1. Travel for an event: search_events (ask for city/month if missing) → search_flights \
around the event dates (ask for the departure city if missing) → create_invoice for the \
chosen flight.
2. Plan a full trip: research/search destinations → add flights, hotels, and activities \
to the itinerary → book_trip.
Both create_invoice and book_trip route to a human approval gate — call them DIRECTLY when \
the traveller asks; the gate is where they confirm, so don't ask "are you sure?" in chat \
first. Never claim an invoice or booking succeeded until you see its tool result.

Guidelines:
- Use tools to answer questions about destinations, flights, hotels, or the traveller's \
bookings — don't guess prices, times, or availability.
- DEFAULT to the quick tools (get_destination_info, search_destinations, \
search_attractions, search_flights, search_hotels) and answer conversationally. They're \
fast and cover almost everything. Only escalate to research_destination when the \
traveller explicitly wants a deep, written research pass (see above) — when a quick tool \
will do, use it.
- IDs come from the search tools. research_destination returns place/neighborhood \
NAMES, not IDs — after researching, call search_flights / search_hotels / \
search_attractions to get the exact IDs, then use those for add_to_itinerary.
- add_to_itinerary takes items as {{kind, id}} where kind is "flight", "hotel", or \
"activity" and id is the ID from the matching search tool.
- BE DECISIVE about adding to the itinerary. When the traveller asks to add something \
("add those", "add the island legs", "sort out Santorini"), don't just list options and \
wait — pick sensible defaults (the cheapest suitable flight, a well-rated hotel within \
budget, 1–2 signature activities), call the needed search tools to get their IDs, and \
add them right away with add_to_itinerary. Then give a one-line summary of what you \
added and invite changes. Only ask the traveller to choose when they've asked to, or a \
choice is genuinely consequential.
- When the traveller adds a destination or leg to the trip, assemble the WHOLE leg in one \
go: a flight to get there (for a Greek island, the inter-island hop — e.g. Athens→Santorini, \
Santorini→Mykonos), a place to stay for the nights involved, and 1–2 things to do. Look \
each up and add them together, then summarize the leg.
- When the traveller asks to book (or to invoice a chosen flight), call book_trip / \
create_invoice RIGHT AWAY. Do not summarize the itinerary and ask "shall I confirm?" first \
— that pre-confirmation is redundant because the tool opens a confirmation gate the \
traveller approves. Just call the tool.
- A named destination means "plan me a trip". When the traveller names a place — whether a \
bare "Tokyo", "plan a trip to X", or "book a trip to X" — don't stop at quick facts and ask \
"want me to find flights?". Give a one- or two-line intro if useful, then GO AHEAD and \
assemble a trip: search flights, a hotel, and 1–2 signature attractions, pick sensible \
defaults (cheapest suitable flight, a well-rated hotel in budget), and add_to_itinerary. \
Summarize the staged trip in a line or two and invite tweaks. If they said "book", go \
straight to book_trip after staging — the approval gate is where they confirm. Ask for a \
detail (like departure city) only when it's genuinely needed and you can't pick a sensible \
default.
- Keep replies short and conversational. This is a chat, not an essay.
- If a tool returns an error, explain the problem plainly and suggest a next step."""


TOOLS = [
    {
        "name": "search_events",
        "description": (
            "Find events — festivals, concerts, sports, conferences — at a destination, "
            "optionally in a given month. Returns events with names, categories, and date "
            "ranges. The entry point for 'I want to travel for an event': find what's on, "
            "then search flights around the event's dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "City or country"},
                "month": {"type": "string", "description": "Optional month, e.g. 'March' or '3'"},
            },
            "required": ["destination"],
        },
    },
    {
        "name": "search_destinations",
        "description": (
            "Search the destination catalog by city, country, region, or interest "
            "(tags like beach/food/nature/nightlife). Returns matching destinations "
            "with their IDs, region, best season, average daily budget, and tags. "
            "Call this when the traveller asks where they could go."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text, e.g. 'beaches in Europe' or 'Japan' or 'food'",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_destination_info",
        "description": (
            "Quick facts about ONE destination plus its top attractions "
            "(best season, average daily budget, tags). Use for a specific place."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "City or country name"}
            },
            "required": ["destination"],
        },
    },
    {
        "name": "search_flights",
        "description": (
            "Search flights to a destination. Destination is required; origin (city or "
            "airport code) and depart_date (YYYY-MM-DD) narrow the results. Returns "
            "flights with IDs, airline, times, stops, and price (cheapest first). "
            "Flights are available on ANY date — pass whatever depart_date the traveller "
            "wants (or omit it) and results come back either way, so never tell the "
            "traveller a date is unavailable. Origins include San Francisco (SFO), Los "
            "Angeles (LAX), New York (JFK), Chicago (ORD), Seattle (SEA), Atlanta (ATL), "
            "Miami (MIA), London (LHR), Paris (CDG), Frankfurt (FRA), Madrid (MAD), Dubai "
            "(DXB), Singapore (SIN), Hong Kong (HKG), and Sydney (SYD). If the traveller "
            "doesn't give an origin, ask or search without one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "Destination city or airport code"},
                "origin": {"type": "string", "description": "Origin city or airport code (optional)"},
                "depart_date": {"type": "string", "description": "YYYY-MM-DD (optional; any date works)"},
            },
            "required": ["destination"],
        },
    },
    {
        "name": "search_hotels",
        "description": (
            "Find hotels at a destination. Returns hotels with IDs, area, star rating, "
            "guest rating, and nightly price (cheapest first). Optionally cap the "
            "nightly price."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "Destination city or country"},
                "max_price": {"type": "number", "description": "Max nightly price (optional)"},
            },
            "required": ["destination"],
        },
    },
    {
        "name": "search_attractions",
        "description": (
            "List things to do at a destination — attractions with IDs, category, "
            "typical cost, and how long they take. Use when planning day activities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "Destination city or country"}
            },
            "required": ["destination"],
        },
    },
    {
        "name": "research_destination",
        "description": (
            "SLOW, heavy multi-step research pass: plan ~6 web searches, run them in "
            "parallel, and return a long synthesized, cited guide. Reserve it for when "
            "the traveller EXPLICITLY asks to research / go deep / do a deep dive / get a "
            "full written guide or comparison. For a named place, quick facts, or routine "
            "planning use get_destination_info and the search tools instead. When in "
            "doubt, offer this pass rather than calling it. Provide a focused, "
            "self-contained research question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A focused, self-contained question, e.g. '5 days in Tokyo for first-timers who love food'",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_invoice",
        "description": (
            "Generate an invoice for ONE flight the traveller has chosen — the finish of "
            "the 'pick a flight → invoice me' flow. Call this directly once they pick a "
            "flight — they approve at a confirmation gate that opens after you call it, so "
            "don't ask 'are you sure?' in chat first. Provide the total amount and a short, "
            "human-readable flight description (airline, route, dates, flight numbers)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Total invoice amount in USD"},
                "flight_details": {
                    "type": "string",
                    "description": "Flight summary, e.g. 'Air New Zealand LAX→AKL, out NZ5 / return NZ6'",
                },
            },
            "required": ["amount", "flight_details"],
        },
    },
    {
        "name": "add_to_itinerary",
        "description": (
            "Add flights, hotels, and/or activities to the traveller's itinerary. "
            "Each item is {kind, id}: kind is 'flight', 'hotel', or 'activity' and id "
            "is the ID from the matching search tool. Staging only — nothing is booked "
            "until book_trip."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["flight", "hotel", "activity"]},
                            "id": {"type": "integer"},
                        },
                        "required": ["kind", "id"],
                    },
                    "description": "Items to add, e.g. [{\"kind\":\"flight\",\"id\":12},{\"kind\":\"hotel\",\"id\":3}]",
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "remove_from_itinerary",
        "description": (
            "Remove items from the itinerary by their item_id (the 'kind-id' string, "
            "e.g. 'flight-12' or 'hotel-3')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "item_ids to remove, e.g. ['flight-12', 'hotel-3']",
                }
            },
            "required": ["item_ids"],
        },
    },
    {
        "name": "book_trip",
        "description": (
            "Book everything currently in the itinerary. Call this directly as soon as the "
            "traveller asks to book — they approve at a confirmation gate that opens after "
            "you call it, so don't ask 'are you sure?' in chat first. After approval a "
            "durable checkout workflow books each item and compensates completed work if a "
            "later booking fails. Explain a compensated result plainly. No arguments needed."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_bookings",
        "description": (
            "List the traveller's booked trips with dates and totals. Uses the signed-in "
            "traveller's account — no arguments needed."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_booking_details",
        "description": "Get the line items (flights, hotels, activities) of one booking by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {"booking_id": {"type": "integer", "description": "Booking ID"}},
            "required": ["booking_id"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# research_destination pipeline prompts + JSON schemas.
#
# Native Claude, no agent framework: the "planner" and "writer" are just system
# prompts + a forced JSON-schema response (structured outputs). The "searcher"
# is a plain message with Claude's built-in web_search tool.
# ─────────────────────────────────────────────────────────────────────────────


def plan_system(count: int) -> str:
    return f"""You are a travel research planner. Given a research brief about a \
destination or trip, produce a set of focused web searches that together will answer it.

- Produce exactly {count} searches — distinct angles that together cover the trip.
- Each search MUST target a DIFFERENT facet, e.g.: top attractions & highlights, best \
neighborhoods / where to stay, food & dining scene, getting around & transport, best \
time to visit & weather, day trips nearby, budget & typical costs, safety & practical \
tips. Do not repeat facets.
- Keep each query concise and search-engine friendly."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "searches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["query", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["searches"],
    "additionalProperties": False,
}


SEARCH_SYSTEM = """You are a travel research assistant. Use web search to investigate \
the given query, then write a concise, factual summary (1–2 paragraphs, under 250 words) \
of the most relevant findings. Capture specific facts: place and neighborhood names, \
signature dishes, prices, seasons, and travel times. Ignore fluff. Do not add commentary \
about your process."""


WRITE_SYSTEM = """You are a senior travel writer. You are given a research brief and a \
set of summarized findings from independent web searches. Synthesize them into one \
cohesive destination guide.

- markdown_report: a tight, well-structured guide in Markdown (headings, short \
paragraphs, and a table of highlights — e.g. attractions, neighborhoods, or costs — \
where useful). Aim for 250–400 words. Ground every claim in the findings; do not \
invent facts.
- short_summary: 2–3 sentences a reader could skim first."""

WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "short_summary": {"type": "string"},
        "markdown_report": {"type": "string"},
    },
    "required": ["short_summary", "markdown_report"],
    "additionalProperties": False,
}
