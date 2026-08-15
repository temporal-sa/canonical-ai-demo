"""External checkout steps used by ``CheckoutWorkflow``.

These small Activities stand in for airline, hotel, and attraction APIs. Their
reservation IDs are idempotent so an Activity retry cannot create a duplicate.
The hotel failure is enabled by default for the live compensation demo; set
``CHECKOUT_FAIL_HOTEL=false`` to exercise the successful checkout path.
"""

import hashlib
import time

from temporalio import activity
from temporalio.exceptions import ApplicationError

import config
from models.types import (
    CheckoutRequest,
    CheckoutReservation,
    CheckoutStepRequest,
)

from . import db


def _pause() -> None:
    """Make the individual steps easy to see on the Temporal timeline."""
    if config.CHECKOUT_STEP_DELAY_SECONDS > 0:
        time.sleep(config.CHECKOUT_STEP_DELAY_SECONDS)


def _reservation(req: CheckoutStepRequest) -> CheckoutReservation:
    # A real integration would pass this key to the provider. Deriving it from
    # stable business identifiers gives this demo the same retry-safe behavior.
    raw = f"{req.account_key}:{req.item.kind}:{req.item.ref_id}".encode()
    suffix = hashlib.sha256(raw).hexdigest()[:10].upper()
    prefix = {"flight": "FLT", "hotel": "HTL", "activity": "ACT"}[req.item.kind]
    return CheckoutReservation(
        kind=req.item.kind,
        ref_id=req.item.ref_id,
        title=req.item.title,
        reservation_id=f"{prefix}-{suffix}",
    )


@activity.defn
def book_flight(req: CheckoutStepRequest) -> CheckoutReservation:
    _pause()
    return _reservation(req)


@activity.defn
def book_hotel(req: CheckoutStepRequest) -> CheckoutReservation:
    _pause()
    if config.CHECKOUT_FAIL_HOTEL:
        raise ApplicationError(
            "Hotel booking failed — the supplier returned no availability "
            "(injected demo failure).",
            type="HotelBookingFailed",
            non_retryable=True,
        )
    return _reservation(req)


@activity.defn
def book_activity(req: CheckoutStepRequest) -> CheckoutReservation:
    _pause()
    return _reservation(req)


def _cancel(reservation: CheckoutReservation) -> CheckoutReservation:
    _pause()
    return reservation.model_copy(update={"status": "cancelled"})


@activity.defn
def cancel_flight(reservation: CheckoutReservation) -> CheckoutReservation:
    return _cancel(reservation)


@activity.defn
def cancel_hotel(reservation: CheckoutReservation) -> CheckoutReservation:
    return _cancel(reservation)


@activity.defn
def cancel_activity(reservation: CheckoutReservation) -> CheckoutReservation:
    return _cancel(reservation)


@activity.defn
def finalize_checkout(req: CheckoutRequest) -> dict:
    """Persist the completed trip only after every reservation succeeds."""
    items = [item.model_dump() for item in req.items]
    already = db.items_already_booked(req.account_key, items)
    if already:
        names = ", ".join(f'"{item["title"]}"' for item in already)
        raise ApplicationError(
            f"Booking declined — this trip already includes {names}.",
            type="BookingDeclined",
            non_retryable=True,
        )
    return db.record_booking(req.account_key, items, req.summary)
