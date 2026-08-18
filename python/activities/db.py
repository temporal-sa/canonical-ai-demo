"""Data module — plain parametrized SQL over the travel dataset (Postgres via psycopg).

One function per tool. No ORM, no abstraction: all data access lives in this
one file, which is what keeps it easy to read (and easy to swap later).

Destinations, flights, hotels, and attractions are read-only seed data. Bookings
are the only writes — created only after human approval, and scoped to a single
conversation via account_key (the workflow ID).
"""

import calendar
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row

import config


def _connect():
    return psycopg.connect(config.DB_URL, row_factory=dict_row)


def _default_flight_date() -> str:
    """A near-future date to show when the traveller didn't name one. Dates in
    this demo are cosmetic — flights are available on any date — so we just
    offer something plausible rather than a fixed (and quickly stale) one."""
    return (date.today() + timedelta(days=21)).isoformat()


def _rebase_event_dates(start_iso: str, end_iso: str) -> tuple[str, str]:
    """Shift a seeded event's fixed year forward so it always reads as upcoming.
    Keeps the real month/day (festivals stay seasonal) and preserves the span,
    which is what keeps the demo evergreen into 2027 and beyond."""
    start, end = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    today = date.today()
    # this year's occurrence if it hasn't started yet, else next year's
    target_year = today.year if start.replace(year=today.year) >= today else today.year + 1
    delta = target_year - start.year
    return (start.replace(year=start.year + delta).isoformat(),
            end.replace(year=end.year + delta).isoformat())


def _month_num(month) -> int | None:
    """Parse a month from a name ('March'), abbrev ('Mar'), number (3), or a
    YYYY-MM / YYYY-MM-DD string. Returns 1–12 or None."""
    if not month:
        return None
    s = str(month).strip().lower()
    names = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
    abbr = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
    if s in names:
        return names[s]
    if s in abbr:
        return abbr[s]
    parts = s.split("-")
    try:
        if len(parts) >= 2:          # YYYY-MM or YYYY-MM-DD
            return int(parts[1])
        v = int(s)
        return v if 1 <= v <= 12 else None
    except ValueError:
        return None


# ── destinations ─────────────────────────────────────────────────────────────
def search_destinations(query: str) -> list[dict]:
    sql = """
        SELECT destination_id, city, country, region, airport_code,
               summary, best_season, avg_daily_budget, tags
        FROM destination
        WHERE city ILIKE %(q)s OR country ILIKE %(q)s OR region ILIKE %(q)s
           OR tags ILIKE %(q)s OR summary ILIKE %(q)s
        ORDER BY city
        LIMIT 15
    """
    with _connect() as conn:
        return conn.execute(sql, {"q": f"%{query}%"}).fetchall()


def get_destination_info(name: str) -> dict:
    """A destination plus its attractions — the 'understand a place' lookup."""
    with _connect() as conn:
        dest = conn.execute(
            """SELECT destination_id, city, country, region, airport_code,
                      summary, best_season, avg_daily_budget, tags
               FROM destination
               WHERE city ILIKE %(q)s OR country ILIKE %(q)s
               ORDER BY city LIMIT 1""",
            {"q": f"%{name}%"},
        ).fetchone()
        if not dest:
            return {"error": f"No destination found matching '{name}'."}
        attractions = conn.execute(
            """SELECT attraction_id, name, category, description, typical_cost, duration_hours
               FROM attraction WHERE destination_id = %(id)s
               ORDER BY attraction_id""",
            {"id": dest["destination_id"]},
        ).fetchall()
        dest["attractions"] = attractions
        return dest


# ── flights ──────────────────────────────────────────────────────────────────
def search_flights(destination: str, origin: str | None = None,
                   depart_date: str | None = None) -> list[dict]:
    """Search seeded flights. Destination is required; origin (city or airport
    code) narrows the results. Cheapest first.

    Dates are intentionally flexible: the route's flights are stamped with the
    requested depart_date (or a near-future default when none is given), so ANY
    date the traveller names returns flights — the demo is never boxed into the
    handful of dates that happen to be seeded."""
    base = ["(dest_city ILIKE %(dest)s OR dest_code ILIKE %(dest_code)s)"]
    params: dict = {"dest": f"%{destination}%", "dest_code": destination}
    if origin:
        base.append("(origin_city ILIKE %(orig)s OR origin_code ILIKE %(orig_code)s)")
        params["orig"] = f"%{origin}%"
        params["orig_code"] = origin

    sql = f"""
        SELECT flight_id, airline, flight_no, origin_city, origin_code,
               dest_city, dest_code, depart_time, arrive_time, duration_min,
               stops, price::float8 AS price, cabin
        FROM flight
        WHERE {' AND '.join(base)}
        ORDER BY price
        LIMIT 12
    """
    eff_date = depart_date or _default_flight_date()
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    for r in rows:
        r["depart_date"] = eff_date  # dates are cosmetic — echo what was asked for
    return rows


# ── events (the "travel for an event" entry point) ────────────────────────────
def search_events(destination: str, month=None) -> list[dict]:
    clauses = ["(d.city ILIKE %(dest)s OR d.country ILIKE %(dest)s)"]
    params: dict = {"dest": f"%{destination}%"}
    m = _month_num(month)
    if m:
        clauses.append("(EXTRACT(MONTH FROM e.start_date) = %(m)s "
                       "OR EXTRACT(MONTH FROM e.end_date) = %(m)s)")
        params["m"] = m
    sql = f"""
        SELECT e.event_id, e.name, e.category,
               e.start_date::text AS start_date, e.end_date::text AS end_date,
               e.description, d.city, d.country
        FROM event e
        JOIN destination d ON d.destination_id = e.destination_id
        WHERE {' AND '.join(clauses)}
        ORDER BY e.start_date
        LIMIT 12
    """
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    for r in rows:
        r["start_date"], r["end_date"] = _rebase_event_dates(r["start_date"], r["end_date"])
    rows.sort(key=lambda r: r["start_date"])  # true upcoming order after rebasing
    return rows


# ── hotels ───────────────────────────────────────────────────────────────────
def search_hotels(destination: str, max_price: float | None = None) -> list[dict]:
    clauses = ["(d.city ILIKE %(dest)s OR d.country ILIKE %(dest)s)"]
    params: dict = {"dest": f"%{destination}%"}
    if max_price is not None:
        clauses.append("h.nightly_price <= %(max)s")
        params["max"] = max_price
    sql = f"""
        SELECT h.hotel_id, h.name, h.area, h.stars, h.rating::float8 AS rating,
               h.nightly_price::float8 AS nightly_price, d.city
        FROM hotel h
        JOIN destination d ON d.destination_id = h.destination_id
        WHERE {' AND '.join(clauses)}
        ORDER BY h.nightly_price
        LIMIT 12
    """
    with _connect() as conn:
        return conn.execute(sql, params).fetchall()


# ── attractions ──────────────────────────────────────────────────────────────
def search_attractions(destination: str) -> list[dict]:
    sql = """
        SELECT a.attraction_id, a.name, a.category, a.description,
               a.typical_cost::float8 AS typical_cost, a.duration_hours::float8 AS duration_hours,
               d.city
        FROM attraction a
        JOIN destination d ON d.destination_id = a.destination_id
        WHERE d.city ILIKE %(dest)s OR d.country ILIKE %(dest)s
        ORDER BY a.attraction_id
        LIMIT 20
    """
    with _connect() as conn:
        return conn.execute(sql, {"dest": f"%{destination}%"}).fetchall()


# ── itinerary item lookup (enrich [{kind, id}] for the durable itinerary) ─────
def get_itinerary_items(items: list[dict]) -> list[dict]:
    """Resolve [{kind, id}] refs into rich itinerary rows (title/subtitle/price).
    Unknown refs are dropped so the model can react to what actually resolved."""
    out: list[dict] = []
    with _connect() as conn:
        for it in items:
            kind, ref = it.get("kind"), it.get("id")
            if kind is None or ref is None:
                continue
            if kind == "flight":
                r = conn.execute(
                    """SELECT flight_id, airline, flight_no, origin_city, dest_city,
                              depart_time, price::float8 AS price
                       FROM flight WHERE flight_id = %s""",
                    (ref,),
                ).fetchone()
                if r:
                    out.append({
                        "kind": "flight", "ref_id": r["flight_id"],
                        "title": f"{r['airline']} {r['flight_no']}",
                        "subtitle": f"{r['origin_city']} → {r['dest_city']} · {_default_flight_date()} {r['depart_time']}",
                        "price": r["price"],
                    })
            elif kind == "hotel":
                r = conn.execute(
                    """SELECT h.hotel_id, h.name, h.area, h.stars,
                              h.nightly_price::float8 AS price, d.city
                       FROM hotel h JOIN destination d ON d.destination_id = h.destination_id
                       WHERE h.hotel_id = %s""",
                    (ref,),
                ).fetchone()
                if r:
                    out.append({
                        "kind": "hotel", "ref_id": r["hotel_id"], "title": r["name"],
                        "subtitle": f"{r['area']}, {r['city']} · {r['stars']}★ · ${r['price']:.0f}/night",
                        "price": r["price"],
                    })
            elif kind == "activity":
                r = conn.execute(
                    """SELECT a.attraction_id, a.name, a.category,
                              a.typical_cost::float8 AS price, d.city
                       FROM attraction a JOIN destination d ON d.destination_id = a.destination_id
                       WHERE a.attraction_id = %s""",
                    (ref,),
                ).fetchone()
                if r:
                    out.append({
                        "kind": "activity", "ref_id": r["attraction_id"], "title": r["name"],
                        "subtitle": f"{r['category']} · {r['city']}",
                        "price": r["price"],
                    })
    return out


# ── bookings (the only writes; per-conversation, human-approved) ─────────────
def get_bookings(account_key: str) -> list[dict]:
    sql = """
        SELECT b.booking_id, b.created_at::date::text AS date,
               b.total::float8 AS total, b.summary,
               count(l.booking_line_id)::int AS item_count
        FROM booking b
        LEFT JOIN booking_line l ON l.booking_id = b.booking_id
        WHERE b.account_key = %(account_key)s
        GROUP BY b.booking_id, b.created_at, b.total, b.summary
        ORDER BY b.created_at DESC, b.booking_id DESC
        LIMIT 10
    """
    with _connect() as conn:
        return conn.execute(sql, {"account_key": account_key}).fetchall()


def get_booking_details(booking_id: int) -> list[dict]:
    sql = """
        SELECT kind, ref_id, title, price::float8 AS price
        FROM booking_line WHERE booking_id = %(id)s
        ORDER BY booking_line_id
    """
    with _connect() as conn:
        return conn.execute(sql, {"id": booking_id}).fetchall()


def items_already_booked(account_key: str, items: list[dict]) -> list[dict]:
    """Which (kind, ref_id) items this conversation already booked. Used to
    decline a duplicate booking — you can't book the same flight/hotel twice."""
    if not items:
        return []
    pairs = [(it["kind"], it["ref_id"]) for it in items]
    sql = """
        SELECT DISTINCT l.kind, l.ref_id, l.title
        FROM booking_line l
        JOIN booking b ON b.booking_id = l.booking_id
        WHERE b.account_key = %(account_key)s
          AND (l.kind, l.ref_id) IN (SELECT kind, ref_id FROM unnest(
                %(kinds)s::text[], %(refs)s::int[]) AS t(kind, ref_id))
        ORDER BY l.kind, l.ref_id
    """
    with _connect() as conn:
        return conn.execute(sql, {
            "account_key": account_key,
            "kinds": [p[0] for p in pairs],
            "refs": [p[1] for p in pairs],
        }).fetchall()


def record_invoice(account_key: str, amount: float, flight_details: str) -> dict:
    """The terminal action of the flight-booking flow (CreateInvoice). Records an
    invoice for the chosen flight, scoped to this conversation. Called only from
    an activity, and only after the traveller confirms."""
    with _connect() as conn:
        invoice_id = conn.execute(
            "SELECT coalesce(max(invoice_id), 0) + 1 AS id FROM invoice"
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO invoice (invoice_id, account_key, created_at, amount, flight_details)
               VALUES (%s, %s, now(), %s, %s)""",
            (invoice_id, account_key, float(amount), flight_details),
        )
        return {"invoice_id": invoice_id, "amount": float(amount),
                "flight_details": flight_details, "status": "invoiced"}


def record_booking(account_key: str, items: list[dict], summary: str) -> dict:
    """The side effect: create a booking + line items. Called only from an
    activity, and only after human approval. Keyed on account_key (the workflow
    ID) so each conversation is self-contained — no seeding, no reset needed."""
    if not items:
        raise ValueError("Nothing to book — the itinerary is empty.")
    total = round(sum(float(it.get("price") or 0) for it in items), 2)
    with _connect() as conn:  # context manager wraps this in one transaction
        booking_id = conn.execute(
            "SELECT coalesce(max(booking_id), 0) + 1 AS id FROM booking"
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO booking (booking_id, account_key, created_at, total, summary)
               VALUES (%s, %s, now(), %s, %s)""",
            (booking_id, account_key, total, summary),
        )
        line_id = conn.execute(
            "SELECT coalesce(max(booking_line_id), 0) AS id FROM booking_line"
        ).fetchone()["id"]
        for it in items:
            line_id += 1
            conn.execute(
                """INSERT INTO booking_line (booking_line_id, booking_id, kind, ref_id,
                                             title, price)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (line_id, booking_id, it["kind"], it["ref_id"],
                 it.get("title", ""), float(it.get("price") or 0)),
            )
        return {
            "booking_id": booking_id,
            "items": [{"kind": it["kind"], "ref_id": it["ref_id"],
                       "title": it.get("title", ""), "price": float(it.get("price") or 0)}
                      for it in items],
            "total": total,
        }
