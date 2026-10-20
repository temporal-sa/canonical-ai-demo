"""External checkout steps used by ``CheckoutWorkflow``.

These small Activities stand in for airline, hotel, and attraction APIs. The
workflow mints each reservation ID and passes it in as the idempotency key, so
an Activity retry returns the same reservation instead of creating a duplicate,
and a cancel can target a booking whose outcome the workflow never heard.
The first checkout's hotel failure is enabled by default for the live
compensation demo; later attempts succeed. Set ``CHECKOUT_FAIL_HOTEL=false``
to skip the injected failure entirely.
"""

import time

from temporalio import activity
from temporalio.exceptions import ApplicationError

import config
from models.types import (
    CheckoutReservation,
    CheckoutStepRequest,
    FinalizeRequest,
)

from . import db


def _pause() -> None:
    """Make the individual steps easy to see on the Temporal timeline."""
    if config.CHECKOUT_STEP_DELAY_SECONDS > 0:
        time.sleep(config.CHECKOUT_STEP_DELAY_SECONDS)


def _reservation(req: CheckoutStepRequest) -> CheckoutReservation:
    # A real integration sends req.reservation_id to the supplier as its
    # idempotency key; the supplier returns the existing reservation on a retry.
    return CheckoutReservation(
        kind=req.item.kind,
        ref_id=req.item.ref_id,
        title=req.item.title,
        reservation_id=req.reservation_id,
    )


@activity.defn
def book_flight(req: CheckoutStepRequest) -> CheckoutReservation:
    _pause()
    return _reservation(req)


@activity.defn
def book_hotel(req: CheckoutStepRequest) -> CheckoutReservation:
    _pause()
    if config.CHECKOUT_FAIL_HOTEL and req.simulate_hotel_failure:
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
    # Cancel by reservation ID. Idempotent: cancelling twice, or cancelling a
    # reservation the supplier never made, succeeds without doing anything.
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
def finalize_checkout(req: FinalizeRequest) -> dict:
    """Persist the completed trip only after every reservation succeeds.

    Idempotent on checkout_id. If an earlier attempt committed and then the
    worker died or timed out before reporting back, the retry finds that booking
    and returns it. Without this check the retry would see the trip's own items
    and decline them as duplicates, and the saga would cancel a trip that was
    booked."""
    if existing := db.booking_for_checkout(req.checkout_id):
        return existing
    checkout = req.checkout
    items = [item.model_dump() for item in checkout.items]
    already = db.items_already_booked(checkout.account_key, items)
    if already:
        names = ", ".join(f'"{item["title"]}"' for item in already)
        raise ApplicationError(
            f"Booking declined — this trip already includes {names}.",
            type="BookingDeclined",
            non_retryable=True,
        )
    return db.record_booking(checkout.account_key, items, checkout.summary, req.checkout_id)


@activity.defn
def void_booking(checkout_id: str) -> int:
    """Compensation for finalize_checkout: remove the checkout's booking record.
    Only runs when finalize's outcome is unknown; a no-op if nothing was written."""
    return db.void_booking(checkout_id)
