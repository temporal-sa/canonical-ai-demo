// Data module — plain parametrized SQL over the travel dataset (Postgres via pg).
// Ported from python/activities/db.py: one function per tool, no ORM.
//
// Destinations, flights, hotels, and attractions are read-only seed data.
// Bookings are the only writes — created only after human approval, and scoped
// to a single conversation via accountKey (the workflow ID).
//
// Notes on the port: psycopg named params (%(x)s) become pg positional params
// ($1, $2, …). Date columns are cast ::text in SQL (as in Python) so rows are
// plain JSON — no Date objects to serialize. `float8` casts come back as JS
// numbers; uncast NUMERIC comes back as a string (same as Python's Decimal via
// json default=str), which is fine for model-facing tool results.

import { Pool } from 'pg';
import * as config from '../config';

// Business errors (e.g. nothing to book) are model-visible tool results, NOT
// activity failures — tools.ts catches this and hands the message to the model.
export class BusinessError extends Error {}

const pool = new Pool({ connectionString: config.DB_URL });

async function q<T = Record<string, unknown>>(sql: string, params: unknown[] = []): Promise<T[]> {
  const res = await pool.query(sql, params);
  return res.rows as T[];
}

const MONTH_NAMES = [
  'january', 'february', 'march', 'april', 'may', 'june',
  'july', 'august', 'september', 'october', 'november', 'december',
];
const MONTH_ABBR = MONTH_NAMES.map((m) => m.slice(0, 3));

// Parse a month from a name ('March'), abbrev ('Mar'), number (3), or a
// YYYY-MM / YYYY-MM-DD string. Returns 1–12 or null.
function monthNum(month?: string | number | null): number | null {
  if (month === undefined || month === null || month === '') return null;
  const s = String(month).trim().toLowerCase();
  let i = MONTH_NAMES.indexOf(s);
  if (i >= 0) return i + 1;
  i = MONTH_ABBR.indexOf(s);
  if (i >= 0) return i + 1;
  const parts = s.split('-');
  if (parts.length >= 2) {
    const v = parseInt(parts[1], 10); // YYYY-MM or YYYY-MM-DD
    return Number.isNaN(v) ? null : v;
  }
  const v = parseInt(s, 10);
  return !Number.isNaN(v) && v >= 1 && v <= 12 ? v : null;
}

// ── destinations ─────────────────────────────────────────────────────────────
export async function searchDestinations(query: string): Promise<Record<string, unknown>[]> {
  const sql = `
    SELECT destination_id, city, country, region, airport_code,
           summary, best_season, avg_daily_budget, tags
    FROM destination
    WHERE city ILIKE $1 OR country ILIKE $1 OR region ILIKE $1
       OR tags ILIKE $1 OR summary ILIKE $1
    ORDER BY city
    LIMIT 15`;
  return q(sql, [`%${query}%`]);
}

export async function getDestinationInfo(name: string): Promise<Record<string, unknown>> {
  const dest = (
    await q(
      `SELECT destination_id, city, country, region, airport_code,
              summary, best_season, avg_daily_budget, tags
       FROM destination
       WHERE city ILIKE $1 OR country ILIKE $1
       ORDER BY city LIMIT 1`,
      [`%${name}%`]
    )
  )[0];
  if (!dest) return { error: `No destination found matching '${name}'.` };
  const attractions = await q(
    `SELECT attraction_id, name, category, description, typical_cost, duration_hours
     FROM attraction WHERE destination_id = $1
     ORDER BY attraction_id`,
    [dest.destination_id]
  );
  return { ...dest, attractions };
}

// ── flights ──────────────────────────────────────────────────────────────────
// Destination is required; origin and depart_date narrow the results. Date
// handling is tolerant: exact day → same calendar month → any date on the route.
export async function searchFlights(
  destination: string,
  origin?: string | null,
  departDate?: string | null
): Promise<Record<string, unknown>[]> {
  const base = ['(dest_city ILIKE $1 OR dest_code ILIKE $2)'];
  const params: unknown[] = [`%${destination}%`, destination];
  if (origin) {
    base.push(`(origin_city ILIKE $${params.length + 1} OR origin_code ILIKE $${params.length + 2})`);
    params.push(`%${origin}%`, origin);
  }

  const run = (extraClauses: string[], extraParams: unknown[]) => {
    const where = [...base, ...extraClauses].join(' AND ');
    const sql = `
      SELECT flight_id, airline, flight_no, origin_city, origin_code,
             dest_city, dest_code, depart_date::text AS depart_date,
             depart_time, arrive_time, duration_min, stops,
             price::float8 AS price, cabin
      FROM flight
      WHERE ${where}
      ORDER BY price
      LIMIT 12`;
    return q(sql, [...params, ...extraParams]);
  };

  if (departDate) {
    let rows = await run([`depart_date = $${params.length + 1}`], [departDate]);
    if (rows.length) return rows;
    rows = await run([`to_char(depart_date, 'YYYY-MM') = $${params.length + 1}`], [departDate.slice(0, 7)]);
    if (rows.length) return rows;
  }
  return run([], []);
}

// ── events (the "travel for an event" entry point) ────────────────────────────
export async function searchEvents(
  destination: string,
  month?: string | number | null
): Promise<Record<string, unknown>[]> {
  const clauses = ['(d.city ILIKE $1 OR d.country ILIKE $1)'];
  const params: unknown[] = [`%${destination}%`];
  const m = monthNum(month);
  if (m) {
    clauses.push('(EXTRACT(MONTH FROM e.start_date) = $2 OR EXTRACT(MONTH FROM e.end_date) = $2)');
    params.push(m);
  }
  const sql = `
    SELECT e.event_id, e.name, e.category,
           e.start_date::text AS start_date, e.end_date::text AS end_date,
           e.description, d.city, d.country
    FROM event e
    JOIN destination d ON d.destination_id = e.destination_id
    WHERE ${clauses.join(' AND ')}
    ORDER BY e.start_date
    LIMIT 12`;
  return q(sql, params);
}

// ── hotels ───────────────────────────────────────────────────────────────────
export async function searchHotels(
  destination: string,
  maxPrice?: number | null
): Promise<Record<string, unknown>[]> {
  const clauses = ['(d.city ILIKE $1 OR d.country ILIKE $1)'];
  const params: unknown[] = [`%${destination}%`];
  if (maxPrice !== undefined && maxPrice !== null) {
    clauses.push('h.nightly_price <= $2');
    params.push(maxPrice);
  }
  const sql = `
    SELECT h.hotel_id, h.name, h.area, h.stars, h.rating::float8 AS rating,
           h.nightly_price::float8 AS nightly_price, d.city
    FROM hotel h
    JOIN destination d ON d.destination_id = h.destination_id
    WHERE ${clauses.join(' AND ')}
    ORDER BY h.nightly_price
    LIMIT 12`;
  return q(sql, params);
}

// ── attractions ──────────────────────────────────────────────────────────────
export async function searchAttractions(destination: string): Promise<Record<string, unknown>[]> {
  const sql = `
    SELECT a.attraction_id, a.name, a.category, a.description,
           a.typical_cost::float8 AS typical_cost, a.duration_hours::float8 AS duration_hours,
           d.city
    FROM attraction a
    JOIN destination d ON d.destination_id = a.destination_id
    WHERE d.city ILIKE $1 OR d.country ILIKE $1
    ORDER BY a.attraction_id
    LIMIT 20`;
  return q(sql, [`%${destination}%`]);
}

// ── itinerary item lookup (enrich [{kind, id}] for the durable itinerary) ─────
// Resolve refs into rich rows (title/subtitle/price). Unknown refs are dropped
// so the model can react to what actually resolved.
export async function getItineraryItems(
  items: { kind?: string; id?: number }[]
): Promise<Record<string, unknown>[]> {
  const out: Record<string, unknown>[] = [];
  for (const it of items) {
    const kind = it.kind;
    const ref = it.id;
    if (kind === undefined || kind === null || ref === undefined || ref === null) continue;
    if (kind === 'flight') {
      const r = (
        await q(
          `SELECT flight_id, airline, flight_no, origin_city, dest_city,
                  depart_date::text AS depart_date, depart_time,
                  price::float8 AS price FROM flight WHERE flight_id = $1`,
          [ref]
        )
      )[0];
      if (r) {
        out.push({
          kind: 'flight',
          ref_id: r.flight_id,
          title: `${r.airline} ${r.flight_no}`,
          subtitle: `${r.origin_city} → ${r.dest_city} · ${r.depart_date} ${r.depart_time}`,
          price: r.price,
        });
      }
    } else if (kind === 'hotel') {
      const r = (
        await q(
          `SELECT h.hotel_id, h.name, h.area, h.stars,
                  h.nightly_price::float8 AS price, d.city
           FROM hotel h JOIN destination d ON d.destination_id = h.destination_id
           WHERE h.hotel_id = $1`,
          [ref]
        )
      )[0];
      if (r) {
        out.push({
          kind: 'hotel',
          ref_id: r.hotel_id,
          title: r.name,
          subtitle: `${r.area}, ${r.city} · ${r.stars}★ · $${Math.round(Number(r.price))}/night`,
          price: r.price,
        });
      }
    } else if (kind === 'activity') {
      const r = (
        await q(
          `SELECT a.attraction_id, a.name, a.category,
                  a.typical_cost::float8 AS price, d.city
           FROM attraction a JOIN destination d ON d.destination_id = a.destination_id
           WHERE a.attraction_id = $1`,
          [ref]
        )
      )[0];
      if (r) {
        out.push({
          kind: 'activity',
          ref_id: r.attraction_id,
          title: r.name,
          subtitle: `${r.category} · ${r.city}`,
          price: r.price,
        });
      }
    }
  }
  return out;
}

// ── bookings (the only writes; per-conversation, human-approved) ─────────────
export async function getBookings(accountKey: string): Promise<Record<string, unknown>[]> {
  const sql = `
    SELECT b.booking_id, b.created_at::date::text AS date,
           b.total::float8 AS total, b.summary,
           count(l.booking_line_id)::int AS item_count
    FROM booking b
    LEFT JOIN booking_line l ON l.booking_id = b.booking_id
    WHERE b.account_key = $1
    GROUP BY b.booking_id, b.created_at, b.total, b.summary
    ORDER BY b.created_at DESC, b.booking_id DESC
    LIMIT 10`;
  return q(sql, [accountKey]);
}

export async function getBookingDetails(bookingId: number): Promise<Record<string, unknown>[]> {
  const sql = `
    SELECT kind, ref_id, title, price::float8 AS price
    FROM booking_line WHERE booking_id = $1
    ORDER BY booking_line_id`;
  return q(sql, [bookingId]);
}

// Which (kind, ref_id) items this conversation already booked — used to decline
// a duplicate booking (you can't book the same flight/hotel twice).
export async function itemsAlreadyBooked(
  accountKey: string,
  items: { kind: string; ref_id: number }[]
): Promise<Record<string, unknown>[]> {
  if (!items.length) return [];
  const kinds = items.map((it) => it.kind);
  const refs = items.map((it) => it.ref_id);
  const sql = `
    SELECT DISTINCT l.kind, l.ref_id, l.title
    FROM booking_line l
    JOIN booking b ON b.booking_id = l.booking_id
    WHERE b.account_key = $1
      AND (l.kind, l.ref_id) IN (SELECT kind, ref_id FROM unnest(
            $2::text[], $3::int[]) AS t(kind, ref_id))
    ORDER BY l.kind, l.ref_id`;
  return q(sql, [accountKey, kinds, refs]);
}

// The terminal action of the flight-booking flow. Records an invoice for the
// chosen flight, scoped to this conversation. Called only after confirmation.
export async function recordInvoice(
  accountKey: string,
  amount: number,
  flightDetails: string
): Promise<Record<string, unknown>> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const invoiceId = (
      await client.query('SELECT coalesce(max(invoice_id), 0) + 1 AS id FROM invoice')
    ).rows[0].id;
    await client.query(
      `INSERT INTO invoice (invoice_id, account_key, created_at, amount, flight_details)
       VALUES ($1, $2, now(), $3, $4)`,
      [invoiceId, accountKey, Number(amount), flightDetails]
    );
    await client.query('COMMIT');
    return {
      invoice_id: invoiceId,
      amount: Number(amount),
      flight_details: flightDetails,
      status: 'invoiced',
    };
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}

// Create a booking + line items. Called only after human approval. Keyed on
// accountKey (the workflow ID) so each conversation is self-contained.
export async function recordBooking(
  accountKey: string,
  items: { kind: string; ref_id: number; title?: string; price?: number }[],
  summary: string
): Promise<Record<string, unknown>> {
  if (!items.length) throw new BusinessError('Nothing to book — the itinerary is empty.');
  const total = round2(items.reduce((s, it) => s + Number(it.price ?? 0), 0));
  const client = await pool.connect();
  try {
    await client.query('BEGIN'); // one transaction
    const bookingId = (
      await client.query('SELECT coalesce(max(booking_id), 0) + 1 AS id FROM booking')
    ).rows[0].id;
    await client.query(
      `INSERT INTO booking (booking_id, account_key, created_at, total, summary)
       VALUES ($1, $2, now(), $3, $4)`,
      [bookingId, accountKey, total, summary]
    );
    let lineId = (
      await client.query('SELECT coalesce(max(booking_line_id), 0) AS id FROM booking_line')
    ).rows[0].id;
    for (const it of items) {
      lineId += 1;
      await client.query(
        `INSERT INTO booking_line (booking_line_id, booking_id, kind, ref_id, title, price)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [lineId, bookingId, it.kind, it.ref_id, it.title ?? '', Number(it.price ?? 0)]
      );
    }
    await client.query('COMMIT');
    return {
      booking_id: bookingId,
      items: items.map((it) => ({
        kind: it.kind,
        ref_id: it.ref_id,
        title: it.title ?? '',
        price: Number(it.price ?? 0),
      })),
      total,
    };
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
