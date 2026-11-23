import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder

from .. import db, notify, queries
from ..realtime import hub, publish_capacity, publish_venue
from ..security import can_manage, current_user, optional_user, require_roles

router = APIRouter(prefix="/api/v1", tags=["Events"])
EDITABLE = ("title", "description", "category", "venue_id", "group_id", "starts_at", "ends_at", "capacity", "price_ngwee")


def _dt(value: str) -> datetime:
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise HTTPException(422, "Timestamps must include a timezone offset")
    return d


def _check_event_rules(data: dict) -> None:
    """Business rules the JSON Schema cannot express (cross-field and database lookups)."""
    starts, ends = data["starts_at"], data["ends_at"]
    errs = []
    if starts <= datetime.now(timezone.utc):
        errs.append({"field": "/starts_at", "message": "Start time must be in the future"})
    if ends <= starts:
        errs.append({"field": "/ends_at", "message": "End time must be after the start time"})
    elif ends - starts > timedelta(hours=24):
        errs.append({"field": "/ends_at", "message": "Events can last at most 24 hours"})
    venue = db.fetch_one("SELECT capacity FROM venues WHERE id = %s AND active", (data["venue_id"],))
    if venue is None:
        errs.append({"field": "/venue_id", "message": "Unknown venue"})
    elif data["capacity"] > venue["capacity"]:
        errs.append({"field": "/capacity", "message": f"Capacity exceeds the venue limit of {venue['capacity']}"})
    if data.get("group_id") and not db.fetch_one("SELECT 1 FROM groups WHERE id = %s", (data["group_id"],)):
        errs.append({"field": "/group_id", "message": "Unknown group"})
    if errs:
        raise HTTPException(422, {"detail": "Event violates a business rule", "errors": errs})


def _visible(event: dict | None, user: dict | None) -> dict:
    if event is None:
        raise HTTPException(404, "Event not found")
    if event["status"] != "published" and not (user and can_manage(user, event["organizer_id"])):
        raise HTTPException(404, "Event not found")
    return event


@router.get("/events")
def list_events(request: Request):
    p = request.query_params
    page = queries.search_events(
        q=p.get("q") or None, category=p.get("category") or None, group=p.get("group") or None,
        venue=int(p["venue"]) if p.get("venue") else None,
        date_from=date.fromisoformat(p["from"]) if p.get("from") else None,
        date_to=date.fromisoformat(p["to"]) if p.get("to") else None,
        available=p.get("available") in ("true", "1"), free=p.get("free") in ("true", "1"),
        page=int(p.get("page", 1)), per_page=int(p.get("per_page", 12)))
    payload = json.dumps(jsonable_encoder(page), separators=(",", ":")).encode()
    etag = '"' + hashlib.sha256(payload).hexdigest()[:20] + '"'
    cache = {"ETag": etag, "Cache-Control": "public, max-age=15, stale-while-revalidate=60"}
    if request.headers.get("if-none-match") == etag:            # Lab 9: conditional GET
        return Response(status_code=304, headers=cache)
    return Response(payload, media_type="application/json", headers=cache)


@router.get("/events/{id}")
def get_event(id: int, user: dict | None = Depends(optional_user)):
    return _visible(queries.get_event(id), user)


@router.post("/events", status_code=201)
def create_event(request: Request, user: dict = Depends(require_roles("organizer", "admin"))):
    b = dict(request.state.json)
    b["starts_at"], b["ends_at"] = _dt(b["starts_at"]), _dt(b["ends_at"])
    _check_event_rules(b)
    row = db.fetch_one("""
        INSERT INTO events (organizer_id, group_id, venue_id, title, description, category,
                            starts_at, ends_at, capacity, price_ngwee)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (user["id"], b.get("group_id"), b["venue_id"], b["title"].strip(), b["description"].strip(),
         b["category"], b["starts_at"], b["ends_at"], b["capacity"], b.get("price_ngwee", 0)))
    return queries.get_event(row["id"])


@router.patch("/events/{id}")
def update_event(id: int, request: Request, user: dict = Depends(current_user)):
    event = queries.get_event(id)
    if event is None or not can_manage(user, event["organizer_id"]):
        raise HTTPException(404, "Event not found")
    if event["status"] not in ("draft", "rejected"):
        raise HTTPException(409, f"A {event['status']} event cannot be edited; cancel it or wait for review")
    b = dict(request.state.json)
    merged = {"venue_id": event["venue"]["id"], "group_id": event["group"]["id"] if event["group"] else None,
              "starts_at": event["starts_at"], "ends_at": event["ends_at"], "capacity": event["capacity"]}
    for k in ("starts_at", "ends_at"):
        if k in b:
            b[k] = _dt(b[k])
    merged.update(b)
    _check_event_rules(merged)
    cols = [k for k in EDITABLE if k in b]                       # column names come from a fixed allow-list
    db.execute(f"UPDATE events SET {', '.join(f'{c} = %s' for c in cols)}, status = 'draft', updated_at = now() "
               "WHERE id = %s", (*[b[c].strip() if isinstance(b[c], str) else b[c] for c in cols], id))
    return queries.get_event(id)


@router.post("/events/{id}/submit", status_code=201)
def submit_event(id: int, request: Request, user: dict = Depends(current_user)):
    b = request.state.json
    with db.transaction() as conn:
        ev = conn.execute("""
            SELECT e.*, v.capacity AS venue_capacity, v.name AS venue_name
            FROM events e JOIN venues v ON v.id = e.venue_id WHERE e.id = %s FOR UPDATE OF e""", (id,)).fetchone()
        if ev is None or ev["organizer_id"] != user["id"]:
            raise HTTPException(404, "Event not found")
        if ev["status"] not in ("draft", "rejected"):
            raise HTTPException(409, f"Event is already {ev['status']}")
        if ev["starts_at"] <= datetime.now(timezone.utc):
            raise HTTPException(422, "Event start time has already passed; edit the date first")
        if b["expected_attendance"] > ev["venue_capacity"]:
            raise HTTPException(422, {"detail": "Attendance exceeds venue capacity", "errors": [
                {"field": "/expected_attendance",
                 "message": f"{ev['venue_name']} holds at most {ev['venue_capacity']} people"}]})
        booking = conn.execute("""
            INSERT INTO venue_bookings (event_id, venue_id, requested_by, starts_at, ends_at,
                                        expected_attendance, requirements)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (id, ev["venue_id"], user["id"], ev["starts_at"], ev["ends_at"], b["expected_attendance"],
             b.get("requirements", []))).fetchone()
        conn.execute("UPDATE events SET status = 'pending', updated_at = now() WHERE id = %s", (id,))
        notify.queue(conn, user["id"], "booking_submitted", {
            "title": ev["title"], "venue": ev["venue_name"],
            "when": ev["starts_at"].astimezone(queries.LUSAKA).strftime("%a %d %b %Y, %H:%M")})
    publish_venue(ev["venue_id"], "booking_requested")
    return queries.get_booking(booking["id"])


@router.post("/events/{id}/cancel")
def cancel_event(id: int, user: dict = Depends(current_user)):
    with db.transaction() as conn:
        ev = conn.execute("SELECT * FROM events WHERE id = %s FOR UPDATE", (id,)).fetchone()
        if ev is None or not can_manage(user, ev["organizer_id"]):
            raise HTTPException(404, "Event not found")
        if ev["status"] == "cancelled":
            raise HTTPException(409, "Event is already cancelled")
        if ev["ends_at"] <= datetime.now(timezone.utc):
            raise HTTPException(409, "Past events cannot be cancelled")
        conn.execute("UPDATE venue_bookings SET status = 'cancelled' WHERE event_id = %s AND status IN "
                     "('pending', 'approved')", (id,))
        holders = conn.execute("""
            UPDATE tickets SET status = 'cancelled' WHERE event_id = %s AND status = 'confirmed'
            RETURNING user_id, code, payment_id""", (id,)).fetchall()
        conn.execute("UPDATE payments SET status = 'refunded', completed_at = now() "
                     "WHERE id = ANY(%s) AND status = 'succeeded'",
                     ([h["payment_id"] for h in holders if h["payment_id"]],))
        conn.execute("UPDATE events SET status = 'cancelled', tickets_sold = 0, updated_at = now() WHERE id = %s",
                     (id,))
        when = ev["starts_at"].astimezone(queries.LUSAKA).strftime("%a %d %b %Y, %H:%M")
        for h in holders:
            notify.queue(conn, h["user_id"], "event_cancelled", {"title": ev["title"], "when": when, "code": h["code"]})
    publish_capacity(id)
    publish_venue(ev["venue_id"], "event_cancelled")
    hub.publish("live", {"type": "event_status", "event_id": id, "status": "cancelled"})
    return queries.get_event(id)


@router.get("/events/{id}/attendees")
def attendees(id: int, user: dict = Depends(current_user)):
    event = queries.get_event(id)
    if event is None or not can_manage(user, event["organizer_id"]):
        raise HTTPException(404, "Event not found")
    return db.fetch_all("""
        SELECT t.code AS ticket_code, u.full_name, u.email, t.payment_id IS NOT NULL AS paid, t.created_at
        FROM tickets t JOIN users u ON u.id = t.user_id
        WHERE t.event_id = %s AND t.status = 'confirmed' ORDER BY t.created_at""", (id,))


@router.get("/recommendations")
def recommendations(request: Request, user: dict = Depends(current_user)):
    return queries.recommendations(user["id"], int(request.query_params.get("limit", 6)))


@router.get("/organizer/events")
def my_events(user: dict = Depends(require_roles("organizer", "admin"))):
    return queries.organizer_events(user["id"])
