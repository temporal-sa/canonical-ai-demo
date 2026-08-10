"""The EXECUTE TOOLS step (slide 28, primitive 03): tool calls as an Activity.

One dispatch over the tools → the plain SQL functions in db.py.
Sync code (psycopg) — the worker runs it on a thread pool.

Business errors (unknown destination, bad IDs) return as model-visible tool
results so the agent can explain them; they are NOT activity failures.
Infrastructure errors (DB down) raise → Temporal retries the activity.
"""

import json

from temporalio import activity
from temporalio.exceptions import ApplicationError

from . import db
from models.types import ToolRequest


def _settle_booking(account_key: str, items: list[dict], summary: str) -> dict:
    """Book the itinerary with one business rule: you can't book the same flight
    or hotel twice.

    That's the UNRECOVERABLE failure — a non-retryable BookingDeclined that
    Temporal does NOT retry (contrast the LLM kill-switch, which IS retried).
    The workflow surfaces it to the traveller and the conversation continues.
    """
    already = db.items_already_booked(account_key, items)
    if already:
        names = ", ".join(f'"{a["title"]}"' for a in already)
        raise ApplicationError(
            f"Booking declined — this trip already includes {names}.",
            type="BookingDeclined",
            non_retryable=True,
        )
    return db.record_booking(account_key, items, summary)


@activity.defn
def execute_tool(req: ToolRequest) -> str:
    name, args = req.call.name, req.call.args
    try:
        if name == "search_events":
            result = db.search_events(args["destination"], args.get("month"))
        elif name == "search_destinations":
            result = db.search_destinations(args["query"])
        elif name == "get_destination_info":
            result = db.get_destination_info(args["destination"])
        elif name == "search_flights":
            result = db.search_flights(
                args["destination"], args.get("origin"), args.get("depart_date")
            )
        elif name == "search_hotels":
            result = db.search_hotels(args["destination"], args.get("max_price"))
        elif name == "search_attractions":
            result = db.search_attractions(args["destination"])
        elif name == "get_bookings":
            result = db.get_bookings(req.account_key)
        elif name == "get_booking_details":
            result = db.get_booking_details(args["booking_id"])
        elif name == "add_to_itinerary":
            # Just the lookup — the workflow owns itinerary STATE (durable,
            # conversation-scoped). Unknown refs are dropped so the model reacts.
            result = db.get_itinerary_items(args["items"])
        elif name == "book_trip":
            result = _settle_booking(req.account_key, args["items"], args.get("summary", ""))
        elif name == "create_invoice":
            # Runs only after the traveller confirms (the workflow gates it).
            result = db.record_invoice(req.account_key, args["amount"], args["flight_details"])
        else:
            raise ApplicationError(f"Unknown tool: {name}", non_retryable=True)
    except ValueError as e:
        return json.dumps({"error": str(e)})  # business error → the model handles it
    return json.dumps(result, default=str)
