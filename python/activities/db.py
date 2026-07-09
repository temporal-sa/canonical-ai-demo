"""Data module — plain parametrized SQL over the music-store dataset (Postgres via psycopg).

One function per tool. No ORM, no abstraction: all data access lives in this
one file, which is what keeps it easy to read (and easy to swap later).
"""

import psycopg
from psycopg.rows import dict_row

import config


def _connect():
    return psycopg.connect(config.DB_URL, row_factory=dict_row)


def search_music(query: str) -> list[dict]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist, al.title AS album,
               t.unit_price::float8 AS price
        FROM track t
        JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE t.name ILIKE %(q)s OR ar.name ILIKE %(q)s OR al.title ILIKE %(q)s
        ORDER BY ar.name, al.title, t.track_id
        LIMIT 15
    """
    with _connect() as conn:
        return conn.execute(sql, {"q": f"%{query}%"}).fetchall()


def search_music_by_genre(genre: str) -> list[dict]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist, al.title AS album,
               t.unit_price::float8 AS price
        FROM track t
        JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE t.name ILIKE %(q)s OR ar.name ILIKE %(q)s OR al.title ILIKE %(q)s
        ORDER BY ar.name, al.title, t.track_id
        LIMIT 15
    """
    with _connect() as conn:
        return conn.execute(sql, {"q": f"%{genre}%"}).fetchall()

def search_music_by_album(album: str) -> list[dict]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist, al.title AS album,
               t.unit_price::float8 AS price
        FROM track t
        JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE t.name ILIKE %(q)s OR ar.name ILIKE %(q)s OR al.title ILIKE %(q)s
        ORDER BY ar.name, al.title, t.track_id
        LIMIT 15
    """
    with _connect() as conn:
        return conn.execute(sql, {"q": f"%{album}%"}).fetchall()

def search_music_by_artist(artist: str) -> list[dict]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist, al.title AS album,
               t.unit_price::float8 AS price
        FROM track t
        JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE t.name ILIKE %(q)s OR ar.name ILIKE %(q)s OR al.title ILIKE %(q)s
        ORDER BY ar.name, al.title, t.track_id
        LIMIT 15
    """
    with _connect() as conn:
        return conn.execute(sql, {"q": f"%{artist}%"}).fetchall()


def get_track_price(track_name: str) -> list[dict]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist,
               t.unit_price::float8 AS price
        FROM track t
        JOIN album al ON al.album_id = t.album_id
        JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE t.name ILIKE %(name)s
        ORDER BY t.track_id
        LIMIT 5
    """
    with _connect() as conn:
        return conn.execute(sql, {"name": f"%{track_name}%"}).fetchall()


def get_customer_orders(email: str) -> list[dict]:
    sql = """
        SELECT i.invoice_id, i.invoice_date::date::text AS date,
               i.total::float8 AS total, count(l.invoice_line_id)::int AS track_count
        FROM invoice i
        JOIN customer c ON c.customer_id = i.customer_id
        LEFT JOIN invoice_line l ON l.invoice_id = i.invoice_id
        WHERE c.email = %(email)s
        GROUP BY i.invoice_id, i.invoice_date, i.total
        ORDER BY i.invoice_date DESC, i.invoice_id DESC
        LIMIT 10
    """
    with _connect() as conn:
        return conn.execute(sql, {"email": email}).fetchall()


def get_order_details(order_id: int) -> list[dict]:
    sql = """
        SELECT t.track_id, t.name AS track, ar.name AS artist, al.title AS album,
               l.unit_price::float8 AS price, l.quantity
        FROM invoice_line l
        JOIN track t ON t.track_id = l.track_id
        LEFT JOIN album al ON al.album_id = t.album_id
        LEFT JOIN artist ar ON ar.artist_id = al.artist_id
        WHERE l.invoice_id = %(order_id)s
        ORDER BY l.invoice_line_id
    """
    with _connect() as conn:
        return conn.execute(sql, {"order_id": order_id}).fetchall()


def tracks_owned(email: str, track_ids: list[int]) -> list[dict]:
    """Which of these track_ids the customer already purchased (id + name).
    Used to decline a duplicate purchase — you can't buy what you already own."""
    if not track_ids:
        return []
    sql = """
        SELECT DISTINCT t.track_id, t.name AS track
        FROM invoice_line l
        JOIN invoice i ON i.invoice_id = l.invoice_id
        JOIN customer c ON c.customer_id = i.customer_id
        JOIN track t ON t.track_id = l.track_id
        WHERE c.email = %(email)s AND l.track_id = ANY(%(ids)s)
        ORDER BY t.track_id
    """
    with _connect() as conn:
        return conn.execute(sql, {"email": email, "ids": track_ids}).fetchall()


def record_purchase(email: str, track_ids: list[int]) -> dict:
    """The side effect: create an invoice + line items. Called only from an
    activity, and only after human approval."""
    with _connect() as conn:  # context manager wraps this in one transaction
        cust = conn.execute(
            """SELECT customer_id, address, city, state, country, postal_code
               FROM customer WHERE email = %s""",
            (email,),
        ).fetchone()
        if not cust:
            # First purchase from a new (e.g. Google-authenticated) email —
            # create the customer so isolation-by-email works without seeding.
            new_id = conn.execute(
                "SELECT coalesce(max(customer_id), 0) + 1 AS id FROM customer"
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO customer (customer_id, first_name, last_name, email)
                   VALUES (%s, %s, %s, %s)""",
                (new_id, (email.split("@")[0] or "Demo")[:40], "Customer", email),
            )
            cust = {"customer_id": new_id, "address": None, "city": None,
                    "state": None, "country": None, "postal_code": None}

        tracks = conn.execute(
            "SELECT track_id, name, unit_price FROM track WHERE track_id = ANY(%s)",
            (track_ids,),
        ).fetchall()
        if not tracks:
            raise ValueError(f"No tracks found for IDs {track_ids}")

        total = sum(t["unit_price"] for t in tracks)
        invoice_id = conn.execute(
            "SELECT coalesce(max(invoice_id), 0) + 1 AS id FROM invoice"
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO invoice (invoice_id, customer_id, invoice_date, billing_address,
                                    billing_city, billing_state, billing_country,
                                    billing_postal_code, total)
               VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s)""",
            (invoice_id, cust["customer_id"], cust["address"], cust["city"],
             cust["state"], cust["country"], cust["postal_code"], total),
        )
        line_id = conn.execute(
            "SELECT coalesce(max(invoice_line_id), 0) AS id FROM invoice_line"
        ).fetchone()["id"]
        for t in tracks:
            line_id += 1
            conn.execute(
                """INSERT INTO invoice_line (invoice_line_id, invoice_id, track_id,
                                             unit_price, quantity)
                   VALUES (%s, %s, %s, %s, 1)""",
                (line_id, invoice_id, t["track_id"], t["unit_price"]),
            )

        return {
            "invoice_id": invoice_id,
            "tracks": [{"track_id": t["track_id"], "name": t["name"],
                        "price": float(t["unit_price"])} for t in tracks],
            "total": float(total),
        }
