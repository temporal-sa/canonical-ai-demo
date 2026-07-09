"""The EXECUTE TOOLS step (slide 28, primitive 03): tool calls as an Activity.

One dispatch over the tools → the plain SQL functions in db.py.
Sync code (psycopg) — the worker runs it on a thread pool.

Business errors (unknown customer, bad track IDs) return as model-visible
tool results so the agent can explain them; they are NOT activity failures.
Infrastructure errors (DB down) raise → Temporal retries the activity.
"""

import json

from temporalio import activity
from temporalio.exceptions import ApplicationError

from . import db
from models.types import ToolRequest


def _settle_purchase(email: str, track_ids: list[int]) -> dict:
    """Checkout with one business rule: you can't buy a track you already own.

    That's the UNRECOVERABLE failure — a non-retryable PurchaseDeclined that
    Temporal does NOT retry (contrast the LLM kill-switch, which IS retried).
    The workflow surfaces it to the customer and the conversation continues.
    """
    owned = db.tracks_owned(email, track_ids)
    if owned:
        names = ", ".join(f'"{o["track"]}"' for o in owned)
        raise ApplicationError(
            f"Purchase declined — the customer already owns {names}.",
            type="PurchaseDeclined",
            non_retryable=True,
        )
    return db.record_purchase(email, track_ids)


@activity.defn
def execute_tool(req: ToolRequest) -> str:
    name, args = req.call.name, req.call.args
    try:
        if name == "search_music":
            result = db.search_music(args["query"])
        elif name == "search_music_by_genre":
            result = db.search_music_by_genre(args["genre"])
        elif name == "search_music_by_artist":
            result = db.search_music_by_artist(args["artist"])
        elif name == "search_music_by_album":
            result = db.search_music_by_album(args["album"])
        elif name == "get_customer_orders":
            result = db.get_customer_orders(req.customer_email)
        elif name == "get_track_price":
            result = db.get_track_price(args["track_name"])
        elif name == "get_order_details":
            result = db.get_order_details(args["order_id"])
        elif name == "purchase_tracks":
            result = _settle_purchase(req.customer_email, args["track_ids"])
        else:
            raise ApplicationError(f"Unknown tool: {name}", non_retryable=True)
    except ValueError as e:
        return json.dumps({"error": str(e)})  # business error → the model handles it
    return json.dumps(result, default=str)
