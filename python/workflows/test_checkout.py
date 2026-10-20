import asyncio
import shutil
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import config
from activities import checkout as checkout_activities
from activities import db
from models.types import (
    CheckoutRequest,
    CheckoutReservation,
    CheckoutStepRequest,
    FinalizeRequest,
    ItineraryItem,
)
from workflows.agent import TravelAgentWorkflow, simulate_hotel_failure_for_attempt
from workflows.checkout import CheckoutWorkflow, reservation_id

FLIGHT = ItineraryItem(kind="flight", ref_id=101, title="Demo Air DA101", price=250)
HOTEL = ItineraryItem(kind="hotel", ref_id=202, title="Demo Hotel", price=200)


# The booking record lives in Postgres, so the workflow tests stub its two steps
# (FinalizeIdempotencyTests covers the real ones) and need no database.
@activity.defn(name="finalize_checkout")
async def stub_finalize(req: FinalizeRequest) -> dict:
    return {"booking_id": 1, "items": [], "total": 0.0}


@activity.defn(name="void_booking")
async def stub_void(checkout_id: str) -> int:
    return 0


ACTIVITIES = {
    "book_flight": checkout_activities.book_flight,
    "book_hotel": checkout_activities.book_hotel,
    "book_activity": checkout_activities.book_activity,
    "cancel_flight": checkout_activities.cancel_flight,
    "cancel_hotel": checkout_activities.cancel_hotel,
    "cancel_activity": checkout_activities.cancel_activity,
    "finalize_checkout": stub_finalize,
    "void_booking": stub_void,
}


def _request(simulate_hotel_failure: bool = True) -> CheckoutRequest:
    return CheckoutRequest(
        account_key="trip-test",
        summary="2 item(s) — $450.00",
        simulate_hotel_failure=simulate_hotel_failure,
        items=[FLIGHT, HOTEL],
    )


def _scheduled(history) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


class CheckoutPolicyTests(unittest.TestCase):
    def test_only_first_attempt_requests_simulated_failure(self) -> None:
        self.assertTrue(simulate_hotel_failure_for_attempt(1))
        self.assertFalse(simulate_hotel_failure_for_attempt(2))

    def test_reservation_ids_are_stable_per_checkout_and_distinct_across_attempts(self) -> None:
        first = reservation_id("trip-x-checkout-1", "HTL", HOTEL)
        self.assertEqual(first, reservation_id("trip-x-checkout-1", "HTL", HOTEL))
        # A retry of the trip after compensation must not reuse a cancelled reservation.
        self.assertNotEqual(first, reservation_id("trip-x-checkout-2", "HTL", HOTEL))

    def test_later_attempt_does_not_inject_hotel_failure(self) -> None:
        previous_failure = config.CHECKOUT_FAIL_HOTEL
        previous_delay = config.CHECKOUT_STEP_DELAY_SECONDS
        config.CHECKOUT_FAIL_HOTEL = True
        config.CHECKOUT_STEP_DELAY_SECONDS = 0
        try:
            reservation = checkout_activities.book_hotel(
                CheckoutStepRequest(item=HOTEL, reservation_id="HTL-TEST",
                                    simulate_hotel_failure=False)
            )
        finally:
            config.CHECKOUT_FAIL_HOTEL = previous_failure
            config.CHECKOUT_STEP_DELAY_SECONDS = previous_delay

        self.assertEqual("booked", reservation.status)
        self.assertEqual("HTL-TEST", reservation.reservation_id)


class CheckoutWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporal_path = shutil.which("temporal")
        if temporal_path is None:
            self.skipTest("Temporal CLI is required for workflow tests")
        self.environment = await WorkflowEnvironment.start_local(
            data_converter=pydantic_data_converter,
            dev_server_existing_path=temporal_path,
            dev_server_log_level="error",
        )
        self.previous = (config.CHECKOUT_FAIL_HOTEL, config.CHECKOUT_STEP_DELAY_SECONDS)
        config.CHECKOUT_FAIL_HOTEL = True
        config.CHECKOUT_STEP_DELAY_SECONDS = 0

    async def asyncTearDown(self) -> None:
        config.CHECKOUT_FAIL_HOTEL, config.CHECKOUT_STEP_DELAY_SECONDS = self.previous
        await self.environment.shutdown()

    async def _run(self, request: CheckoutRequest, workflow_id: str, **overrides):
        """Run one checkout, with any activity swapped for a stub.
        Returns (result or raised error, history)."""
        activities = {**ACTIVITIES, **overrides}
        client = self.environment.client
        with ThreadPoolExecutor(max_workers=4) as executor:
            async with Worker(
                client,
                task_queue="checkout-test",
                workflows=[TravelAgentWorkflow, CheckoutWorkflow],
                activities=list(activities.values()),
                activity_executor=executor,
            ):
                handle = await client.start_workflow(
                    CheckoutWorkflow.run, request, id=workflow_id, task_queue="checkout-test"
                )
                try:
                    outcome = await handle.result()
                except WorkflowFailureError as error:
                    outcome = error
                return outcome, await handle.fetch_history()

    async def test_hotel_failure_compensates_booked_flight(self) -> None:
        result, history = await self._run(_request(), "checkout-compensation-test")

        self.assertEqual("compensated", result.status)
        self.assertIn("Hotel booking failed", result.failure)
        self.assertEqual(["flight"], [item.kind for item in result.reservations])
        self.assertEqual(["cancelled"], [item.status for item in result.compensations])
        self.assertEqual(
            result.reservations[0].reservation_id,
            result.compensations[0].reservation_id,
        )
        # The hotel declined outright, so there's nothing to cancel for it.
        self.assertEqual(["book_flight", "book_hotel", "cancel_flight"], _scheduled(history))

    async def test_step_with_unknown_outcome_is_compensated_too(self) -> None:
        @activity.defn(name="book_hotel")
        async def hotel_times_out(req: CheckoutStepRequest) -> CheckoutReservation:
            raise ApplicationError("supplier timed out", type="SupplierTimeout")

        result, history = await self._run(
            _request(simulate_hotel_failure=False), "checkout-unknown-outcome-test",
            book_hotel=hotel_times_out,
        )

        self.assertEqual("compensated", result.status)
        # The hotel may have been booked before the timeout, so cancel it, newest first.
        self.assertEqual(["hotel", "flight"], [r.kind for r in result.compensations])
        self.assertEqual(
            ["book_flight", "book_hotel", "cancel_hotel", "cancel_flight"], _scheduled(history)
        )

    async def test_compensation_retries_past_the_forward_step_limit(self) -> None:
        @activity.defn(name="cancel_flight")
        async def flaky_cancel(reservation: CheckoutReservation) -> CheckoutReservation:
            if activity.info().attempt <= 3:  # forward steps would have given up here
                raise ApplicationError("airline API unavailable", type="SupplierDown")
            return reservation.model_copy(update={"status": "cancelled"})

        result, _ = await self._run(
            _request(), "checkout-compensation-retry-test", cancel_flight=flaky_cancel
        )

        self.assertEqual("compensated", result.status)
        self.assertEqual(["cancelled"], [r.status for r in result.compensations])

    async def test_cancelled_checkout_compensates_then_stays_cancelled(self) -> None:
        hotel_started = asyncio.Event()

        @activity.defn(name="book_hotel")
        async def slow_hotel(req: CheckoutStepRequest) -> CheckoutReservation:
            hotel_started.set()
            await asyncio.sleep(2)
            return CheckoutReservation(kind="hotel", ref_id=req.item.ref_id,
                                       title=req.item.title, reservation_id=req.reservation_id)

        async def cancel_when_hotel_starts():
            await hotel_started.wait()
            await self.environment.client.get_workflow_handle("checkout-cancel-test").cancel()

        canceller = asyncio.create_task(cancel_when_hotel_starts())
        outcome, history = await self._run(
            _request(simulate_hotel_failure=False), "checkout-cancel-test", book_hotel=slow_hotel
        )
        await canceller

        self.assertIsInstance(outcome, WorkflowFailureError)
        self.assertIsInstance(outcome.cause, CancelledError)
        self.assertEqual(
            ["book_flight", "book_hotel", "cancel_hotel", "cancel_flight"], _scheduled(history)
        )


class FinalizeIdempotencyTests(unittest.TestCase):
    """Against the demo's Postgres (`docker compose up postgres`); skipped without it."""

    def setUp(self) -> None:
        try:
            with psycopg.connect(config.DB_URL, connect_timeout=2) as conn:
                conn.execute("SELECT checkout_id FROM booking LIMIT 0")
        except psycopg.Error as error:
            self.skipTest(f"needs the demo Postgres with the current schema: {error}")
        self.account = f"trip-test-{uuid.uuid4().hex[:8]}"
        self.request = CheckoutRequest(account_key=self.account, summary="test", items=[FLIGHT])

    def tearDown(self) -> None:
        with psycopg.connect(config.DB_URL) as conn:
            conn.execute("DELETE FROM booking_line WHERE booking_id IN "
                         "(SELECT booking_id FROM booking WHERE account_key = %s)", (self.account,))
            conn.execute("DELETE FROM booking WHERE account_key = %s", (self.account,))
            conn.execute("DELETE FROM invoice WHERE account_key = %s", (self.account,))

    def test_retry_after_commit_returns_the_same_booking(self) -> None:
        req = FinalizeRequest(checkout_id=f"{self.account}-checkout-1", checkout=self.request)
        first = checkout_activities.finalize_checkout(req)
        retried = checkout_activities.finalize_checkout(req)  # the result we never heard back
        self.assertEqual(first["booking_id"], retried["booking_id"])

    def test_a_different_checkout_of_the_same_items_is_declined(self) -> None:
        checkout_activities.finalize_checkout(
            FinalizeRequest(checkout_id=f"{self.account}-checkout-1", checkout=self.request))
        with self.assertRaises(ApplicationError) as raised:
            checkout_activities.finalize_checkout(
                FinalizeRequest(checkout_id=f"{self.account}-checkout-2", checkout=self.request))
        self.assertEqual("BookingDeclined", raised.exception.type)

    def test_void_booking_is_idempotent(self) -> None:
        checkout_id = f"{self.account}-checkout-1"
        checkout_activities.finalize_checkout(
            FinalizeRequest(checkout_id=checkout_id, checkout=self.request))
        self.assertEqual(1, checkout_activities.void_booking(checkout_id))
        self.assertEqual(0, checkout_activities.void_booking(checkout_id))

    def test_a_retried_invoice_returns_the_same_invoice(self) -> None:
        key = f"{self.account}-invoice-1"
        first = db.record_invoice(self.account, 250.0, "DA101", idempotency_key=key)
        retried = db.record_invoice(self.account, 250.0, "DA101", idempotency_key=key)
        self.assertEqual(first["invoice_id"], retried["invoice_id"])


if __name__ == "__main__":
    unittest.main()
