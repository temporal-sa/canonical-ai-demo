"""Data module — plain parametrized SQL over the travel dataset (Postgres via psycopg).

One function per tool. No ORM, no abstraction: all data access lives in this
one file, which is what keeps it easy to read (and easy to swap later).

Destinations, flights, hotels, and attractions are read-only seed data. Bookings
are the only writes — created only after human approval, and scoped to a single
conversation via account_key (the workflow ID).
"""

import calendar
import hashlib
import random
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


# ── fabricated offers (flights & hotels) ─────────────────────────────────────
# Flights and hotels are generated on demand from the traveller's request, not
# seeded — so ANY city/route/date returns results and a demoer can plan any trip.
# Each offer is deterministic (seeded by its route/city), so a retry returns the
# same offers and IDs. We upsert each into the flight/hotel table purely so the
# existing id-based add_to_itinerary → book_trip round-trip resolves unchanged —
# the DB is just an ephemeral external store here, and nothing outside this file
# (workflow, tools, prompts) changes. Ids sit in a high band so they never
# collide with any seed rows.

_AIRLINES = [
    ("United", "UA"), ("Delta", "DL"), ("American", "AA"), ("Emirates", "EK"),
    ("Singapore Airlines", "SQ"), ("ANA", "NH"), ("Lufthansa", "LH"),
    ("British Airways", "BA"), ("Qatar Airways", "QR"), ("Cathay Pacific", "CX"),
]
_HOTEL_PREFIXES = ["The Grand", "Park", "Riverside", "Central", "Skyline",
                   "Old Town", "Harbour", "Garden", "Metropole", "Boutique"]
_HOTEL_SUFFIXES = ["Hotel", "Suites", "Inn", "Residence", "Palace", "Lodge"]
_HOTEL_AREAS = ["City Center", "Old Town", "Waterfront", "Downtown",
                "Historic District", "Riverside", "Arts Quarter"]
_CABINS = ["Economy", "Economy", "Economy", "Premium Economy", "Business"]
_CABIN_PREMIUM = {"Economy": 0, "Premium Economy": 220, "Business": 1100}


def _rng(*parts) -> random.Random:
    """Deterministic RNG seeded by a stable string — same request → same offers."""
    return random.Random("|".join(str(p) for p in parts))


def _offer_id(*parts) -> int:
    """Stable id in a high band (seed rows use small ints, so no collisions)."""
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return 1_000_000 + int(h[:15], 16) % 2_000_000_000


def _airport_code(city: str) -> str:
    letters = "".join(c for c in city.upper() if c.isalpha())
    return (letters + "XXX")[:3]


def _hhmm(mins: int) -> str:
    mins %= 24 * 60
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _dest_id_for_city(conn, city: str) -> int:
    """Reuse a seeded destination if the city matches one, else create a minimal
    row (fabricated hotels need a destination_id FK). Deterministic id."""
    row = conn.execute(
        "SELECT destination_id FROM destination WHERE city ILIKE %s ORDER BY destination_id LIMIT 1",
        (f"%{city}%",),
    ).fetchone()
    if row:
        return row["destination_id"]
    dest_id = _offer_id("dest", city.lower())
    conn.execute(
        """INSERT INTO destination (destination_id, city, country, region, airport_code)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (destination_id) DO NOTHING""",
        (dest_id, city, "", "", _airport_code(city)),
    )
    return dest_id


# ── flights ──────────────────────────────────────────────────────────────────
def search_flights(destination: str, origin: str | None = None,
                   depart_date: str | None = None) -> list[dict]:
    """Generate flights for the requested route/date. Always returns options
    (cheapest first) for any origin/destination — origin defaults to a hub when
    the traveller hasn't named one; the date is echoed onto every offer."""
    origin_city = origin or "San Francisco"
    dest_city = destination
    eff_date = depart_date or _default_flight_date()
    origin_code, dest_code = _airport_code(origin_city), _airport_code(dest_city)
    r = _rng("flight", origin_city.lower(), dest_city.lower(), eff_date)

    offers = []
    for i in range(r.randint(4, 6)):
        airline, code = r.choice(_AIRLINES)
        cabin = r.choice(_CABINS)
        depart_min = r.randint(5 * 60, 21 * 60)
        duration = r.randint(90, 16 * 60)
        offers.append({
            "flight_id": _offer_id("flight", origin_city, dest_city, eff_date, i),
            "airline": airline, "flight_no": f"{code}{r.randint(100, 9999)}",
            "origin_city": origin_city, "origin_code": origin_code,
            "dest_city": dest_city, "dest_code": dest_code,
            "depart_time": _hhmm(depart_min), "arrive_time": _hhmm(depart_min + duration),
            "duration_min": duration, "stops": r.choice([0, 0, 0, 1]),
            "price": float(r.randint(180, 900) + _CABIN_PREMIUM[cabin]), "cabin": cabin,
            "depart_date": eff_date,
        })
    offers.sort(key=lambda o: o["price"])

    with _connect() as conn:
        for o in offers:
            conn.execute(
                """INSERT INTO flight (flight_id, airline, flight_no, origin_city,
                       origin_code, dest_city, dest_code, depart_date, depart_time,
                       arrive_time, duration_min, stops, price, cabin)
                   VALUES (%(flight_id)s, %(airline)s, %(flight_no)s, %(origin_city)s,
                       %(origin_code)s, %(dest_city)s, %(dest_code)s, %(depart_date)s,
                       %(depart_time)s, %(arrive_time)s, %(duration_min)s, %(stops)s,
                       %(price)s, %(cabin)s)
                   ON CONFLICT (flight_id) DO NOTHING""",
                o,
            )
    return offers


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
    """Generate hotels for the requested city. Always returns options (cheapest
    first); an optional max_price filters, but never to empty — the cheapest is
    kept so any city still returns a place to stay."""
    city = destination
    r = _rng("hotel", city.lower())
    offers = []
    for i in range(r.randint(4, 6)):
        offers.append({
            "hotel_id": _offer_id("hotel", city.lower(), i),
            "name": f"{r.choice(_HOTEL_PREFIXES)} {city} {r.choice(_HOTEL_SUFFIXES)}",
            "area": r.choice(_HOTEL_AREAS), "stars": r.randint(2, 5),
            "rating": round(r.uniform(3.5, 4.8), 1),
            "nightly_price": float(r.randint(6, 60) * 10), "city": city,
        })
    offers.sort(key=lambda o: o["nightly_price"])
    if max_price is not None:
        within = [o for o in offers if o["nightly_price"] <= max_price]
        offers = within or offers[:1]  # always leave at least the cheapest

    with _connect() as conn:
        dest_id = _dest_id_for_city(conn, city)
        for o in offers:
            conn.execute(
                """INSERT INTO hotel (hotel_id, destination_id, name, area, stars,
                       rating, nightly_price)
                   VALUES (%(hotel_id)s, %(destination_id)s, %(name)s, %(area)s,
                       %(stars)s, %(rating)s, %(nightly_price)s)
                   ON CONFLICT (hotel_id) DO NOTHING""",
                {**o, "destination_id": dest_id},
            )
    return offers


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
