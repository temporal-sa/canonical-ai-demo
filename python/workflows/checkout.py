"""CheckoutWorkflow — reliable execution after the agent has made a decision.

The code is intentionally ordinary: book in order, catch a failure, then undo
the work in reverse order. Temporal makes every step durable and ensures the
compensation still runs after worker crashes or process restarts.

Three rules make the saga safe, and each is one or two lines below:

1. **The workflow mints every idempotency key.** Reservation IDs and the booking
   key derive from this workflow's ID, so a retried step is recognised by the
   supplier, and a later checkout attempt never collides with an earlier one.
2. **Register the undo before the step runs.** A step that times out may or may
   not have happened. Cancelling by ID is safe either way, so the compensation
   is on the stack before the call, and comes off only if the supplier said a
   definite "no".
3. **Compensations must eventually succeed.** They retry without an attempt
   limit. One that keeps failing stays visible as a pending activity with a
   climbing attempt count, which is where an operator steps in.
"""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from activities.checkout import (
        book_activity,
        book_flight,
        book_hotel,
        cancel_activity,
        cancel_flight,
        cancel_hotel,
        finalize_checkout,
        void_booking,
    )
    from models.types import (
        CheckoutRequest,
        CheckoutReservation,
        CheckoutResult,
        CheckoutStepRequest,
        FinalizeRequest,
        ItineraryItem,
    )


# A supplier's definite "no": nothing was booked, so there is nothing to undo
# and no point retrying.
DECLINED = ["HotelBookingFailed", "BookingDeclined"]

# Forward steps: a few quick retries, then give up and compensate.
STEP_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=3,
    non_retryable_error_types=DECLINED,
)

# Compensations: no attempt limit (rule 3).
COMPENSATION_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
)

# Flights first, then hotels, then activities: business ordering, easy to change.
STEPS = (
    ("flight", "FLT", book_flight, cancel_flight),
    ("hotel", "HTL", book_hotel, cancel_hotel),
    ("activity", "ACT", book_activity, cancel_activity),
)


@dataclass
class _Undo:
    activity: Callable
    arg: Any
    summary: str


def reservation_id(checkout_id: str, prefix: str, item: ItineraryItem) -> str:
    """Deterministic, so a replay or a retry produces the same key (rule 1)."""
    raw = f"{checkout_id}:{item.kind}:{item.ref_id}".encode()
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:10].upper()}"


def _declined(error: ActivityError) -> bool:
    cause = error.cause
    return isinstance(cause, ApplicationError) and cause.type in DECLINED


def _stop_if_cancelled() -> None:
    """A step that finishes after a cancel request returns its result, and the
    cancel would be swallowed. Turn it back into a cancellation so that step,
    now on the undo stack, is compensated too."""
    if workflow.cancellation_reason() is not None:
        raise asyncio.CancelledError()


def _failure_message(error: ActivityError) -> str:
    return getattr(error.cause, "message", None) or "Checkout failed."


@workflow.defn
class CheckoutWorkflow:
    """Reserve an itinerary and compensate completed reservations on failure."""

    @workflow.run
    async def run(self, request: CheckoutRequest) -> CheckoutResult:
        checkout_id = workflow.info().workflow_id
        reservations: list[CheckoutReservation] = []
        undo: list[_Undo] = []

        try:
            for kind, prefix, book, cancel in STEPS:
                for item in request.items:
                    if item.kind != kind:
                        continue
                    key = reservation_id(checkout_id, prefix, item)
                    undo.append(_Undo(
                        cancel,
                        CheckoutReservation(kind=kind, ref_id=item.ref_id,
                                            title=item.title, reservation_id=key),
                        f"Cancel {kind}: {item.title}",
                    ))
                    reservations.append(await workflow.execute_activity(
                        book,
                        CheckoutStepRequest(
                            item=item,
                            reservation_id=key,
                            simulate_hotel_failure=request.simulate_hotel_failure,
                        ),
                        start_to_close_timeout=timedelta(seconds=15),  # DB write; fast
                        retry_policy=STEP_RETRY,
                        # If the checkout is cancelled mid-step, wait for the step to
                        # actually stop before compensating, so a cancel can't overtake
                        # the booking it is meant to undo.
                        cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                        summary=f"Book {kind}: {item.title}",
                    ))
                    _stop_if_cancelled()

            undo.append(_Undo(void_booking, checkout_id, "Void booking record"))
            booking = await workflow.execute_activity(
                finalize_checkout,
                FinalizeRequest(checkout_id=checkout_id, checkout=request),
                start_to_close_timeout=timedelta(seconds=15),  # DB write; fast
                retry_policy=STEP_RETRY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                summary="Commit completed trip",
            )
            _stop_if_cancelled()
            return CheckoutResult(
                status="booked",
                message="Checkout completed and every itinerary item is booked.",
                workflow_id=checkout_id,
                reservations=reservations,
                booking_id=booking["booking_id"],
            )
        except ActivityError as error:
            if _declined(error):
                undo.pop()  # a definite "no": that step left nothing behind (rule 2)
            failure = _failure_message(error)
            compensations = await self._compensate(undo)
            # On the demo path the hotel declines after the flight is booked, so
            # this is a single, visible cancel_flight.
            cancelled = ", ".join(r.title for r in compensations) or "no prior reservations"
            return CheckoutResult(
                status="compensated",
                message=(
                    f"Checkout stopped: {failure} "
                    f"Compensation completed: cancelled {cancelled}."
                ),
                workflow_id=checkout_id,
                reservations=reservations,
                compensations=compensations,
                failure=failure,
            )
        except asyncio.CancelledError:
            # Cancelled from outside, e.g. the agent's conversation was closed
            # mid-checkout. Undo everything that may have happened, then stay cancelled.
            await self._compensate(undo)
            raise

    async def _compensate(self, undo: list[_Undo]) -> list[CheckoutReservation]:
        """Run the undo stack in reverse; return the reservations it cancelled."""
        cancelled: list[CheckoutReservation] = []
        for step in reversed(undo):
            result = await workflow.execute_activity(
                step.activity,
                step.arg,
                start_to_close_timeout=timedelta(seconds=15),  # DB write; fast
                retry_policy=COMPENSATION_RETRY,
                summary=step.summary,
            )
            if isinstance(result, CheckoutReservation):
                cancelled.append(result)
        return cancelled
