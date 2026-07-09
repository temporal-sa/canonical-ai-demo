"""The ONE system prompt and the 4 tool definitions (provider-neutral shape).

Tool schemas use the Anthropic-native format (name / description / input_schema);
the OpenAI path in activities/llm.py wraps them into function-call format.
"""


def system_prompt(customer_email: str) -> str:
    return f"""You are a friendly support agent for a digital music store.

The customer you are helping is already authenticated as: {customer_email}

You can help customers:
- find music in the catalog (search_music, search_music_by_genre, search_music_by_artist, search_music_by_album)
- check track prices (get_track_price)
- review their past orders (get_customer_orders)
- buy tracks (purchase_tracks) — this requires human approval; when you call it, the \
purchase is routed to an approver before it completes. Never claim a purchase succeeded \
until you see its tool result.

Guidelines:
- Use tools to answer questions about the catalog or the customer's account — don't guess.
- Track IDs come from search_music results; use those exact IDs when purchasing.
- Before purchasing, confirm with the customer which tracks they want.
- Keep replies short and conversational. This is a chat, not an essay.
- If a tool returns an error, explain the problem plainly and suggest a next step."""


TOOLS = [
    {
        "name": "search_music",
        "description": (
            "Search the music catalog by track name, artist, or album. "
            "Returns matching tracks with their IDs, artist, album, and price. "
            "Call this whenever the customer asks about music."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text, e.g. an artist name like 'AC/DC'",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_music_by_genre",
        "description": "Search the music catalog by genre. Returns matching tracks with their IDs, artist, album, and price.",
        "input_schema": {
            "type": "object",
            "properties": {"genre": {"type": "string", "description": "Genre name"}},
            "required": ["genre"],
        },
    },
    {
        "name": "search_music_by_artist",
        "description": "Search the music catalog by artist. Returns matching tracks with their IDs, artist, album, and price.",
        "input_schema": {
            "type": "object",
            "properties": {"artist": {"type": "string", "description": "Artist name"}},
            "required": ["artist"],
        },
    },
    {
        "name": "search_music_by_album",
        "description": "Search the music catalog by album. Returns matching tracks with their IDs, artist, album, and price.",
        "input_schema": {
            "type": "object",
            "properties": {"album": {"type": "string", "description": "Album name"}},
            "required": ["album"],
        },
    },
    {
        "name": "get_track_price",
        "description": "Look up the price of a specific track by its name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "track_name": {
                    "type": "string",
                    "description": "Exact or partial track name",
                }
            },
            "required": ["track_name"],
        },
    },
    {
        "name": "get_customer_orders",
        "description": (
            "List the customer's recent orders (invoices) with dates and totals. "
            "Uses the authenticated customer's account — no arguments needed."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_order_details",
        "description": "Get the details of a specific order by its ID. Returns the order details with the track names, artist, album, and price.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "integer", "description": "Order ID"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "purchase_tracks",
        "description": (
            "Buy tracks for the authenticated customer. Requires human approval before it "
            "completes. Provide the track IDs (from search_music) and a short summary of "
            "the purchase for the approver."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "IDs of the tracks to purchase",
                },
                "summary": {
                    "type": "string",
                    "description": 'Human-readable summary for the approver, e.g. "2 tracks — $1.98"',
                },
            },
            "required": ["track_ids", "summary"],
        },
    },
]
