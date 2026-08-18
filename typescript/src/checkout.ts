// CheckoutWorkflow — reliable execution after the agent has made a decision.
//
// The control flow is deliberately ordinary: book in order, catch a failure,
// and undo completed work in reverse order. Temporal durably drives every step.

import {
  ActivityFailure,
  ApplicationFailure,
  proxyActivities,
  workflowInfo,
} from '@temporalio/workflow';
import type { RetryPolicy } from '@temporalio/common';
import type * as activities from './activities';
import type {
  CheckoutRequest,
  CheckoutReservation,
  CheckoutResult,
  ItineraryItem,
} from './types';

const CHECKOUT_RETRY: RetryPolicy = {
  initialInterval: '1 second',
  backoffCoefficient: 2,
  maximumInterval: '5 seconds',
  maximumAttempts: 3,
  nonRetryableErrorTypes: ['HotelBookingFailed', 'BookingDeclined'],
};

const checkoutActivities = proxyActivities<typeof activities>({
  startToCloseTimeout: '30 seconds',
  retry: CHECKOUT_RETRY,
});

function failureMessage(error: ActivityFailure): string {
  return error.cause instanceof ApplicationFailure && error.cause.message
    ? error.cause.message
    : 'Checkout failed.';
}

export async function CheckoutWorkflow(request: CheckoutRequest): Promise<CheckoutResult> {
  const reservations: CheckoutReservation[] = [];

  try {
    // Business ordering is explicit and customizable: flights, hotels, then
    // activities. Each function call becomes a durable Activity in history.
    const steps: Array<[
      ItineraryItem['kind'],
      (req: { account_key: string; item: ItineraryItem }) => Promise<CheckoutReservation>,
    ]> = [
      ['flight', checkoutActivities.book_flight],
      ['hotel', checkoutActivities.book_hotel],
      ['activity', checkoutActivities.book_activity],
    ];

    for (const [kind, book] of steps) {
      for (const item of request.items) {
        if (item.kind !== kind) continue;
        reservations.push(await book({ account_key: request.account_key, item }));
      }
    }

    const booking = await checkoutActivities.finalize_checkout(request);
    return {
      status: 'booked',
      message: 'Checkout completed and every itinerary item is booked.',
      workflow_id: workflowInfo().workflowId,
      reservations,
      compensations: [],
      booking_id: booking.booking_id as number,
    };
  } catch (error) {
    if (!(error instanceof ActivityFailure)) throw error;

    const compensations: CheckoutReservation[] = [];
    const cancelByKind = {
      flight: checkoutActivities.cancel_flight,
      hotel: checkoutActivities.cancel_hotel,
      activity: checkoutActivities.cancel_activity,
    };

    // Saga compensation: undo only completed side effects, in reverse order.
    // On the demo path the failed hotel follows a successful flight, so the
    // next event is visibly cancel_flight.
    for (const booked of [...reservations].reverse()) {
      compensations.push(await cancelByKind[booked.kind](booked));
    }

    const cancelled = compensations.map((item) => item.title).join(', ') || 'no prior reservations';
    return {
      status: 'compensated',
      message:
        `Checkout stopped: ${failureMessage(error)} ` +
        `Compensation completed: cancelled ${cancelled}.`,
      workflow_id: workflowInfo().workflowId,
      reservations,
      compensations,
      failure: failureMessage(error),
    };
  }
}
