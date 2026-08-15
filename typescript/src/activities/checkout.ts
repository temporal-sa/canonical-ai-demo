// External checkout steps used by CheckoutWorkflow. These are intentionally
// tiny stand-ins for airline, hotel, and attraction APIs. Stable reservation
// IDs make retries idempotent, just as a provider idempotency key would.

import { createHash } from 'crypto';
import { ApplicationFailure } from '@temporalio/common';

import * as config from '../config';
import type {
  CheckoutRequest,
  CheckoutReservation,
  CheckoutStepRequest,
} from '../types';
import * as db from './db';

async function pause(): Promise<void> {
  if (config.CHECKOUT_STEP_DELAY_MS > 0) {
    await new Promise((resolve) => setTimeout(resolve, config.CHECKOUT_STEP_DELAY_MS));
  }
}

function reservation(req: CheckoutStepRequest): CheckoutReservation {
  const raw = `${req.account_key}:${req.item.kind}:${req.item.ref_id}`;
  const suffix = createHash('sha256').update(raw).digest('hex').slice(0, 10).toUpperCase();
  const prefix = { flight: 'FLT', hotel: 'HTL', activity: 'ACT' }[req.item.kind];
  return {
    kind: req.item.kind,
    ref_id: req.item.ref_id,
    title: req.item.title,
    reservation_id: `${prefix}-${suffix}`,
    status: 'booked',
  };
}

export async function book_flight(req: CheckoutStepRequest): Promise<CheckoutReservation> {
  await pause();
  return reservation(req);
}

export async function book_hotel(req: CheckoutStepRequest): Promise<CheckoutReservation> {
  await pause();
  if (config.CHECKOUT_FAIL_HOTEL) {
    throw ApplicationFailure.create({
      message:
        'Hotel booking failed — the supplier returned no availability (injected demo failure).',
      type: 'HotelBookingFailed',
      nonRetryable: true,
    });
  }
  return reservation(req);
}

export async function book_activity(req: CheckoutStepRequest): Promise<CheckoutReservation> {
  await pause();
  return reservation(req);
}

async function cancel(res: CheckoutReservation): Promise<CheckoutReservation> {
  await pause();
  return { ...res, status: 'cancelled' };
}

export async function cancel_flight(res: CheckoutReservation): Promise<CheckoutReservation> {
  return cancel(res);
}

export async function cancel_hotel(res: CheckoutReservation): Promise<CheckoutReservation> {
  return cancel(res);
}

export async function cancel_activity(res: CheckoutReservation): Promise<CheckoutReservation> {
  return cancel(res);
}

export async function finalize_checkout(req: CheckoutRequest): Promise<Record<string, unknown>> {
  const already = await db.itemsAlreadyBooked(req.account_key, req.items);
  if (already.length) {
    const names = already.map((item) => `"${item.title}"`).join(', ');
    throw ApplicationFailure.create({
      message: `Booking declined — this trip already includes ${names}.`,
      type: 'BookingDeclined',
      nonRetryable: true,
    });
  }
  return db.recordBooking(req.account_key, req.items, req.summary);
}
