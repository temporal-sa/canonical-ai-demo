"""The EXECUTE TOOLS step (slide 28, primitive 03): tool calls as an Activity.

One dispatch over the tools → the plain SQL functions in db.py.
Sync code (psycopg) — the worker runs it on a thread pool.

Business errors (unknown destination, bad IDs) return as model-visible tool
results so the agent can explain them; they are NOT activity failures.
Infrastructure errors (DB down) raise → Temporal retries the activity.
"""

import json
import time

from temporalio import activity
from temporalio.exceptions import ApplicationError

import config
from . import db
from models.types import ToolRequest


@activity.defn
def execute_tool(req: ToolRequest) -> str:
    # Demo pacing beat: DB lookups are instant, so give each tool call a visible
    # moment in the timeline (and a window to kill a worker mid-call). See
    # config.TOOL_DELAY_SECONDS; set it to 0 to disable.
    if config.TOOL_DELAY_SECONDS > 0:
        time.sleep(config.TOOL_DELAY_SECONDS)
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
        elif name == "create_invoice":
            # Runs only after the traveller confirms (the workflow gates it). The
            # workflow mints the idempotency key, so a retry can't invoice twice.
            # (book_trip never reaches here: the workflow runs CheckoutWorkflow.)
            result = db.record_invoice(req.account_key, args["amount"], args["flight_details"],
                                       args["idempotency_key"])
        else:
            raise ApplicationError(f"Unknown tool: {name}", non_retryable=True)
    except ValueError as e:
        return json.dumps({"error": str(e)})  # business error → the model handles it
    return json.dumps(result, default=str)
