"""CheckoutWorkflow — reliable execution after the agent has made a decision.

The code is intentionally ordinary: book in order, catch a failure, then undo
completed work in reverse order. Temporal makes every step durable and ensures
the compensation still runs after worker crashes or process restarts.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from activities.checkout import (
        book_activity,
        book_flight,
        book_hotel,
        cancel_activity,
        cancel_flight,
        cancel_hotel,
        finalize_checkout,
    )
    from models.types import (
        CheckoutRequest,
        CheckoutReservation,
        CheckoutResult,
        CheckoutStepRequest,
    )


CHECKOUT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=3,
    non_retryable_error_types=["HotelBookingFailed", "BookingDeclined"],
)


def _failure_message(error: ActivityError) -> str:
    return getattr(error.cause, "message", None) or "Checkout failed."


@workflow.defn
class CheckoutWorkflow:
    """Reserve an itinerary and compensate completed reservations on failure."""

    @workflow.run
    async def run(self, request: CheckoutRequest) -> CheckoutResult:
        reservations: list[CheckoutReservation] = []

        try:
            # Business ordering is explicit and easy to customize: flights
            # first, then hotels, then activities.
            for kind, booking_activity in (
                ("flight", book_flight),
                ("hotel", book_hotel),
                ("activity", book_activity),
            ):
                for item in request.items:
                    if item.kind != kind:
                        continue
                    reservation = await workflow.execute_activity(
                        booking_activity,
                        CheckoutStepRequest(account_key=request.account_key, item=item),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=CHECKOUT_RETRY,
                        summary=f"Book {kind}: {item.title}",
                    )
                    reservations.append(reservation)

            booking = await workflow.execute_activity(
                finalize_checkout,
                request,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=CHECKOUT_RETRY,
                summary="Commit completed trip",
            )
            return CheckoutResult(
                status="booked",
                message="Checkout completed and every itinerary item is booked.",
                workflow_id=workflow.info().workflow_id,
                reservations=reservations,
                booking_id=booking["booking_id"],
            )
        except ActivityError as error:
            failure = _failure_message(error)
            compensations: list[CheckoutReservation] = []

            # Saga compensation: undo only the side effects that completed,
            # in reverse order. On the demo path the hotel fails after the
            # flight succeeds, so this schedules a visible cancel_flight.
            for reservation in reversed(reservations):
                cancel_activity_for_kind = {
                    "flight": cancel_flight,
                    "hotel": cancel_hotel,
                    "activity": cancel_activity,
                }[reservation.kind]
                compensation = await workflow.execute_activity(
                    cancel_activity_for_kind,
                    reservation,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=CHECKOUT_RETRY,
                    summary=f"Cancel {reservation.kind}: {reservation.title}",
                )
                compensations.append(compensation)

            cancelled = ", ".join(r.title for r in compensations) or "no prior reservations"
            return CheckoutResult(
                status="compensated",
                message=(
                    f"Checkout stopped: {failure} "
                    f"Compensation completed: cancelled {cancelled}."
                ),
                workflow_id=workflow.info().workflow_id,
                reservations=reservations,
                compensations=compensations,
                failure=failure,
            )
