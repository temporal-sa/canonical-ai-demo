import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor

from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from activities import checkout as checkout_activities
from models.types import CheckoutRequest, ItineraryItem
from workflows.agent import TravelAgentWorkflow
from workflows.checkout import CheckoutWorkflow


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

    async def asyncTearDown(self) -> None:
        await self.environment.shutdown()

    async def test_hotel_failure_compensates_booked_flight(self) -> None:
        previous_failure = checkout_activities.config.CHECKOUT_FAIL_HOTEL
        previous_delay = checkout_activities.config.CHECKOUT_STEP_DELAY_SECONDS
        checkout_activities.config.CHECKOUT_FAIL_HOTEL = True
        checkout_activities.config.CHECKOUT_STEP_DELAY_SECONDS = 0
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    self.environment.client,
                    task_queue="checkout-test",
                    workflows=[TravelAgentWorkflow, CheckoutWorkflow],
                    activities=[
                        checkout_activities.book_flight,
                        checkout_activities.book_hotel,
                        checkout_activities.book_activity,
                        checkout_activities.cancel_flight,
                        checkout_activities.cancel_hotel,
                        checkout_activities.cancel_activity,
                        checkout_activities.finalize_checkout,
                    ],
                    activity_executor=executor,
                ):
                    result = await self.environment.client.execute_workflow(
                        CheckoutWorkflow.run,
                        CheckoutRequest(
                            account_key="trip-test",
                            summary="2 item(s) — $450.00",
                            items=[
                                ItineraryItem(
                                    kind="flight",
                                    ref_id=101,
                                    title="Demo Air DA101",
                                    price=250,
                                ),
                                ItineraryItem(
                                    kind="hotel",
                                    ref_id=202,
                                    title="Demo Hotel",
                                    price=200,
                                ),
                            ],
                        ),
                        id="checkout-compensation-test",
                        task_queue="checkout-test",
                    )
                    history = await self.environment.client.get_workflow_handle(
                        "checkout-compensation-test"
                    ).fetch_history()
        finally:
            checkout_activities.config.CHECKOUT_FAIL_HOTEL = previous_failure
            checkout_activities.config.CHECKOUT_STEP_DELAY_SECONDS = previous_delay

        self.assertEqual("compensated", result.status)
        self.assertIn("Hotel booking failed", result.failure)
        self.assertEqual(["flight"], [item.kind for item in result.reservations])
        self.assertEqual(["cancelled"], [item.status for item in result.compensations])
        self.assertEqual(
            result.reservations[0].reservation_id,
            result.compensations[0].reservation_id,
        )
        activity_types = [
            event.activity_task_scheduled_event_attributes.activity_type.name
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
        ]
        self.assertEqual(
            ["book_flight", "book_hotel", "cancel_flight"],
            activity_types,
        )


if __name__ == "__main__":
    unittest.main()
