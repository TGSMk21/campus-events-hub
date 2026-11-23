"""Read queries shared by the JSON API and the server-rendered pages.

All SQL uses bound parameters (%s / %(name)s). Dynamic WHERE clauses are built
from fixed SQL fragments chosen by code; user values only ever travel as
parameters.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import db

LUSAKA = ZoneInfo("Africa/Lusaka")

EVENT_SELECT = """
SELECT e.id, e.title, e.description, e.category, e.starts_at, e.ends_at, e.capacity, e.tickets_sold,
       e.capacity - e.tickets_sold AS seats_left, e.price_ngwee, e.status, e.organizer_id,
       u.full_name AS organizer_name,
       v.id AS venue_id, v.slug AS venue_slug, v.name AS venue_name, v.capacity AS venue_capacity,
       g.id AS group_id, g.slug AS group_slug, g.name AS group_name,
       (SELECT b.status FROM venue_bookings b WHERE b.event_id = e.id ORDER BY b.id DESC LIMIT 1) AS booking_status
FROM events e
JOIN users  u ON u.id = e.organizer_id
JOIN venues v ON v.id = e.venue_id
LEFT JOIN groups g ON g.id = e.group_id
"""


def to_event(r: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": r["id"], "title": r["title"], "description": r["description"], "category": r["category"],
        "venue": {"id": r["venue_id"], "slug": r["venue_slug"], "name": r["venue_name"]},
        "group": {"id": r["group_id"], "slug": r["group_slug"], "name": r["group_name"]} if r["group_id"] else None,
        "organizer_name": r["organizer_name"], "organizer_id": r["organizer_id"],
        "starts_at": r["starts_at"], "ends_at": r["ends_at"], "capacity": r["capacity"],
        "tickets_sold": r["tickets_sold"], "seats_left": r["seats_left"], "price_ngwee": r["price_ngwee"],
        "status": r["status"], "booking_status": r["booking_status"],
    }
    if "score" in r:
        out["score"] = float(r["score"])
        out["reasons"] = r["reasons"]
    return out


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, LUSAKA)


def search_events(q: str | None = None, category: str | None = None, group: str | None = None,
                  venue: int | None = None, date_from: date | None = None, date_to: date | None = None,
                  available: bool = False, free: bool = False, page: int = 1, per_page: int = 12) -> dict:
    where = ["e.status = 'published'", "e.starts_at >= %(start)s"]
    params: dict[str, Any] = {"start": max(datetime.now(timezone.utc),
                                           _day_start(date_from) if date_from else datetime.min.replace(tzinfo=timezone.utc)),
                              "limit": per_page, "offset": (page - 1) * per_page}
    if q:
        where.append("(e.title ILIKE %(q)s OR e.description ILIKE %(q)s)")
        params["q"] = _like(q.strip())
    if category:
        where.append("e.category = %(category)s")
        params["category"] = category
    if group:
        where.append("g.slug = %(group)s")
        params["group"] = group
    if venue:
        where.append("e.venue_id = %(venue)s")
        params["venue"] = venue
    if date_to:
        where.append("e.starts_at < %(end)s")
        params["end"] = _day_start(date_to + timedelta(days=1))
    if available:
        where.append("e.tickets_sold < e.capacity")
    if free:
        where.append("e.price_ngwee = 0")
    sql = (EVENT_SELECT.replace("SELECT e.id", "SELECT COUNT(*) OVER () AS total, e.id", 1)
           + " WHERE " + " AND ".join(where) + " ORDER BY e.starts_at, e.id LIMIT %(limit)s OFFSET %(offset)s")
    rows = db.fetch_all(sql, params)
    total = rows[0]["total"] if rows else 0
    return {"items": [to_event(r) for r in rows], "page": page, "per_page": per_page, "total": total}


def get_event(event_id: int) -> dict[str, Any] | None:
    r = db.fetch_one(EVENT_SELECT + " WHERE e.id = %s", (event_id,))
    return to_event(r) if r else None


def organizer_events(user_id: int) -> list[dict[str, Any]]:
    rows = db.fetch_all(EVENT_SELECT + " WHERE e.organizer_id = %s ORDER BY e.starts_at DESC", (user_id,))
    return [to_event(r) for r in rows]


def recommendations(user_id: int, limit: int = 6) -> list[dict[str, Any]]:
    rows = db.fetch_all(f"""
        WITH me      AS (SELECT interests FROM users WHERE id = %(uid)s),
             past    AS (SELECT DISTINCT e.category FROM tickets t JOIN events e ON e.id = t.event_id
                         WHERE t.user_id = %(uid)s),
             follows AS (SELECT group_id FROM group_follows WHERE user_id = %(uid)s),
             scored  AS (
                SELECT x.*,
                       (x.group_id IS NOT NULL AND x.group_id IN (SELECT group_id FROM follows)) AS r_follow,
                       (x.category = ANY ((SELECT interests FROM me)::text[]))                   AS r_interest,
                       (x.category IN (SELECT category FROM past))                                AS r_past,
                       (x.tickets_sold::float / x.capacity >= 0.5)                                AS r_popular
                FROM ({EVENT_SELECT}
                      WHERE e.status = 'published' AND e.starts_at > now() AND e.tickets_sold < e.capacity
                        AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.event_id = e.id
                                        AND t.user_id = %(uid)s AND t.status = 'confirmed')) x)
        SELECT *, (3 * r_follow::int + 2 * r_interest::int + r_past::int + 0.5 * r_popular::int) AS score
        FROM scored
        ORDER BY score DESC, starts_at
        LIMIT %(limit)s
    """, {"uid": user_id, "limit": limit})
    out = []
    for r in rows:
        reasons = []
        if r["r_follow"]:
            reasons.append(f"You follow {r['group_name']}")
        if r["r_interest"]:
            reasons.append(f"Matches your interest in {r['category']}")
        if r["r_past"]:
            reasons.append(f"You've attended {r['category']} events before")
        if r["r_popular"]:
            reasons.append("Filling up fast")
        r["reasons"] = reasons or ["Coming up soon"]
        out.append(to_event(r))
    return out


# ---------------------------------------------------------------- groups ----

def list_groups(user_id: int | None = None, q: str | None = None, category: str | None = None) -> list[dict]:
    where, params = ["TRUE"], {"uid": user_id or 0}
    if q:
        where.append("(g.name ILIKE %(q)s OR g.description ILIKE %(q)s)")
        params["q"] = _like(q)
    if category:
        where.append("g.category = %(category)s")
        params["category"] = category
    return db.fetch_all(f"""
        SELECT g.id, g.slug, g.name, g.category, g.description, g.meeting_info, g.contact_email,
               (SELECT COUNT(*) FROM group_follows f WHERE f.group_id = g.id)::int AS followers,
               EXISTS (SELECT 1 FROM group_follows f WHERE f.group_id = g.id AND f.user_id = %(uid)s) AS following,
               (SELECT COUNT(*) FROM events e WHERE e.group_id = g.id AND e.status = 'published'
                  AND e.starts_at > now())::int AS upcoming_events
        FROM groups g WHERE {' AND '.join(where)} ORDER BY g.name""", params)


def get_group(slug: str, user_id: int | None = None) -> dict | None:
    rows = [g for g in list_groups(user_id) if g["slug"] == slug]
    return rows[0] if rows else None


# ---------------------------------------------------------------- venues ----

def list_venues() -> list[dict]:
    return db.fetch_all("SELECT id, slug, name, capacity, location, facilities FROM venues WHERE active ORDER BY name")


def venue_slots(venue_id: int, start: datetime, end: datetime) -> list[dict]:
    return db.fetch_all("""
        SELECT b.starts_at, b.ends_at, b.status, e.title AS event_title
        FROM venue_bookings b JOIN events e ON e.id = b.event_id
        WHERE b.venue_id = %s AND b.status IN ('pending', 'approved')
          AND b.starts_at < %s AND b.ends_at > %s
        ORDER BY b.starts_at""", (venue_id, end, start))


# -------------------------------------------------------------- bookings ----

def conflicts_for(conn_or_none, venue_id: int, starts_at: datetime, ends_at: datetime, exclude_event: int) -> list[dict]:
    sql = """
        SELECT b.id AS booking_id, e.title AS event_title, b.status, b.starts_at, b.ends_at
        FROM venue_bookings b JOIN events e ON e.id = b.event_id
        WHERE b.venue_id = %s AND b.status IN ('pending', 'approved') AND b.event_id <> %s
          AND tstzrange(b.starts_at, b.ends_at, '[)') && tstzrange(%s, %s, '[)')
        ORDER BY b.starts_at"""
    params = (venue_id, exclude_event, starts_at, ends_at)
    if conn_or_none is not None:
        return conn_or_none.execute(sql, params).fetchall()
    return db.fetch_all(sql, params)


BOOKING_SELECT = """
SELECT b.id, b.event_id, e.title AS event_title, b.venue_id, v.slug AS venue_slug, v.name AS venue_name,
       b.requested_by, u.full_name AS requested_by_name, b.starts_at, b.ends_at, b.expected_attendance,
       b.requirements, b.status, b.admin_note, b.created_at,
       (SELECT COUNT(*) FROM documents d WHERE d.booking_id = b.id)::int AS documents
FROM venue_bookings b
JOIN events e ON e.id = b.event_id
JOIN venues v ON v.id = b.venue_id
JOIN users  u ON u.id = b.requested_by
"""


def to_booking(r: dict, conflicts: list[dict]) -> dict:
    return {
        "id": r["id"], "event_id": r["event_id"], "event_title": r["event_title"],
        "venue": {"id": r["venue_id"], "slug": r["venue_slug"], "name": r["venue_name"]},
        "requested_by_name": r["requested_by_name"], "starts_at": r["starts_at"], "ends_at": r["ends_at"],
        "expected_attendance": r["expected_attendance"], "requirements": r["requirements"],
        "status": r["status"], "admin_note": r["admin_note"], "created_at": r["created_at"],
        "documents": r["documents"], "conflicts": conflicts,
    }


def get_booking(booking_id: int) -> dict | None:
    r = db.fetch_one(BOOKING_SELECT + " WHERE b.id = %s", (booking_id,))
    if not r:
        return None
    out = to_booking(r, conflicts_for(None, r["venue_id"], r["starts_at"], r["ends_at"], r["event_id"]))
    out["requested_by"] = r["requested_by"]
    return out


def list_bookings(status: str | None, requested_by: int | None) -> list[dict]:
    where, params = ["TRUE"], []
    if status:
        where.append("b.status = %s")
        params.append(status)
    if requested_by is not None:
        where.append("b.requested_by = %s")
        params.append(requested_by)
    rows = db.fetch_all(BOOKING_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY b.created_at DESC LIMIT 200",
                        tuple(params))
    return [to_booking(r, conflicts_for(None, r["venue_id"], r["starts_at"], r["ends_at"], r["event_id"])
                       if r["status"] == "pending" else [])
            for r in rows]


def user_tickets(user_id: int) -> list[dict]:
    rows = db.fetch_all("""
        SELECT t.id, t.code, t.status, t.payment_id IS NOT NULL AS paid, t.created_at,
               e.id AS event_id, e.title, e.starts_at, v.name AS venue_name
        FROM tickets t JOIN events e ON e.id = t.event_id JOIN venues v ON v.id = e.venue_id
        WHERE t.user_id = %s ORDER BY (t.status = 'confirmed') DESC, e.starts_at""", (user_id,))
    return [{"id": r["id"], "code": r["code"], "status": r["status"], "paid": r["paid"], "created_at": r["created_at"],
             "event": {"id": r["event_id"], "title": r["title"], "starts_at": r["starts_at"],
                       "venue_name": r["venue_name"]}} for r in rows]
