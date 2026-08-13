// The EXECUTE TOOLS step: tool calls as an Activity. One dispatch over the tools
// → the plain SQL functions in db.ts. Ported from python/activities/tools.py.
//
// Business errors (unknown destination, bad IDs, empty itinerary) come back as
// model-visible tool results so the agent can explain them; they are NOT
// activity failures. Infrastructure errors (DB down) throw → Temporal retries.
// A duplicate booking is the one UNRECOVERABLE failure — a non-retryable
// BookingDeclined that Temporal does not retry.

import { ApplicationFailure } from '@temporalio/common';

import * as db from './db';
import type { ToolRequest } from '../types';

// Book the itinerary with one business rule: you can't book the same flight or
// hotel twice. That duplicate is the non-retryable BookingDeclined.
async function settleBooking(
  accountKey: string,
  items: { kind: string; ref_id: number; title?: string; price?: number }[],
  summary: string
): Promise<Record<string, unknown>> {
  const already = await db.itemsAlreadyBooked(accountKey, items);
  if (already.length) {
    const names = already.map((a) => `"${a.title}"`).join(', ');
    throw ApplicationFailure.create({
      message: `Booking declined — this trip already includes ${names}.`,
      type: 'BookingDeclined',
      nonRetryable: true,
    });
  }
  return db.recordBooking(accountKey, items, summary);
}

export async function executeTool(req: ToolRequest): Promise<string> {
  const { name, args } = req.call;
  let result: unknown;
  try {
    switch (name) {
      case 'search_events':
        result = await db.searchEvents(args.destination as string, args.month as string | undefined);
        break;
      case 'search_destinations':
        result = await db.searchDestinations(args.query as string);
        break;
      case 'get_destination_info':
        result = await db.getDestinationInfo(args.destination as string);
        break;
      case 'search_flights':
        result = await db.searchFlights(
          args.destination as string,
          args.origin as string | undefined,
          args.depart_date as string | undefined
        );
        break;
      case 'search_hotels':
        result = await db.searchHotels(args.destination as string, args.max_price as number | undefined);
        break;
      case 'search_attractions':
        result = await db.searchAttractions(args.destination as string);
        break;
      case 'get_bookings':
        result = await db.getBookings(req.account_key);
        break;
      case 'get_booking_details':
        result = await db.getBookingDetails(args.booking_id as number);
        break;
      case 'add_to_itinerary':
        // Just the lookup — the workflow owns itinerary STATE (durable,
        // conversation-scoped). Unknown refs are dropped so the model reacts.
        result = await db.getItineraryItems(args.items as { kind?: string; id?: number }[]);
        break;
      case 'book_trip':
        result = await settleBooking(
          req.account_key,
          args.items as { kind: string; ref_id: number; title?: string; price?: number }[],
          (args.summary as string) ?? ''
        );
        break;
      case 'create_invoice':
        // Runs only after the traveller confirms (the workflow gates it).
        result = await db.recordInvoice(
          req.account_key,
          args.amount as number,
          args.flight_details as string
        );
        break;
      default:
        throw ApplicationFailure.create({ message: `Unknown tool: ${name}`, nonRetryable: true });
    }
  } catch (e) {
    if (e instanceof db.BusinessError) {
      return JSON.stringify({ error: e.message }); // business error → the model handles it
    }
    throw e;
  }
  return JSON.stringify(result);
}
