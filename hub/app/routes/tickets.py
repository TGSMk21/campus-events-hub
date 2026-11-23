"""Ticketing and simulated payments (Lab 7, Task 2: multi-step ACID transactions).

Overselling is prevented three ways:
  1. SELECT ... FOR UPDATE on the event row serialises concurrent buyers;
  2. the capacity check runs while holding that lock;
  3. CHECK (tickets_sold <= capacity) in the schema rejects anything that slips through.
Any failure inside `db.transaction()` rolls back the ticket, the counter and the
queued notifications together.
"""
import hashlib
import hmac
import secrets
import string
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import db, notify, queries
from ..config import get_settings
from ..realtime import publish_capacity
from ..security import current_user

router = APIRouter(prefix="/api/v1", tags=["Tickets"])
ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"


def _ticket_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(12))


def _when(ev: dict) -> str:
    return ev["starts_at"].astimezone(queries.LUSAKA).strftime("%a %d %b %Y, %H:%M")


def _lock_event_for_sale(conn: psycopg.Connection, event_id: int, user_id: int) -> dict:
    ev = conn.execute("""
        SELECT e.*, v.name AS venue_name FROM events e JOIN venues v ON v.id = e.venue_id
        WHERE e.id = %s FOR UPDATE OF e""", (event_id,)).fetchone()
    if ev is None or ev["status"] != "published":
        raise HTTPException(404, "Event not found")
    if ev["starts_at"] <= datetime.now(timezone.utc):
        raise HTTPException(409, "This event has already started")
    if ev["tickets_sold"] >= ev["capacity"]:
        raise HTTPException(409, "Sold out")
    if conn.execute("SELECT 1 FROM tickets WHERE event_id = %s AND user_id = %s AND status = 'confirmed'",
                    (event_id, user_id)).fetchone():
        raise HTTPException(409, "You already have a ticket for this event")
    return ev


def _issue_ticket(conn: psycopg.Connection, ev: dict, user_id: int, payment_id: int | None) -> dict:
    ticket = conn.execute("""
        INSERT INTO tickets (code, event_id, user_id, payment_id) VALUES (%s, %s, %s, %s)
        RETURNING id, code, status, created_at""", (_ticket_code(), ev["id"], user_id, payment_id)).fetchone()
    conn.execute("UPDATE events SET tickets_sold = tickets_sold + 1 WHERE id = %s", (ev["id"],))
    notify.queue(conn, user_id, "ticket_confirmed",
                 {"title": ev["title"], "when": _when(ev), "venue": ev["venue_name"], "code": ticket["code"]})
    return ticket


def _ticket_out(ticket: dict, ev: dict, paid: bool) -> dict:
    return {**ticket, "paid": paid,
            "event": {"id": ev["id"], "title": ev["title"], "starts_at": ev["starts_at"], "venue_name": ev["venue_name"]}}


@router.post("/events/{id}/register", status_code=201)
def register(id: int, user: dict = Depends(current_user)):
    with db.transaction() as conn:
        ev = _lock_event_for_sale(conn, id, user["id"])
        if ev["price_ngwee"] > 0:
            raise HTTPException(409, "This is a ticketed event; use checkout")
        ticket = _issue_ticket(conn, ev, user["id"], None)
    publish_capacity(id)
    return _ticket_out(ticket, ev, False)


@router.post("/events/{id}/checkout", status_code=201)
def checkout(id: int, user: dict = Depends(current_user)):
    with db.transaction() as conn:
        ev = _lock_event_for_sale(conn, id, user["id"])
        if ev["price_ngwee"] == 0:
            raise HTTPException(409, "This event is free; register instead")
        p = conn.execute("""
            INSERT INTO payments (public_id, user_id, event_id, amount_ngwee) VALUES (%s, %s, %s, %s)
            RETURNING public_id""", (secrets.token_urlsafe(18), user["id"], id, ev["price_ngwee"])).fetchone()
    return get_payment_out(p["public_id"])


def get_payment_out(public_id: str) -> dict:
    r = db.fetch_one("""
        SELECT p.public_id, p.status, p.amount_ngwee, p.event_id, e.title AS event_title, p.failure_reason,
               p.user_id, (SELECT t.code FROM tickets t WHERE t.payment_id = p.id) AS ticket_code
        FROM payments p JOIN events e ON e.id = p.event_id WHERE p.public_id = %s""", (public_id,))
    if r is None:
        raise HTTPException(404, "Payment not found")
    r["pay_url"] = f"/sandbox/pay/{public_id}"
    return r


def finalize_payment(public_id: str, outcome: str, user_id: int | None = None) -> dict:
    """Idempotent: a payment that is no longer pending is returned unchanged (webhook retries are safe)."""
    event_id = None
    with db.transaction() as conn:
        # Lock order is always event -> payment (same as cancel_event) so concurrent requests cannot deadlock.
        pre = conn.execute("SELECT event_id FROM payments WHERE public_id = %s", (public_id,)).fetchone()
        if pre:
            conn.execute("SELECT 1 FROM events WHERE id = %s FOR UPDATE", (pre["event_id"],))
        pay = conn.execute("SELECT * FROM payments WHERE public_id = %s FOR UPDATE", (public_id,)).fetchone()
        if pay is None or (user_id is not None and pay["user_id"] != user_id):
            raise HTTPException(404, "Payment not found")
        if pay["status"] == "pending":
            ev_row = conn.execute("SELECT e.title FROM events e WHERE e.id = %s", (pay["event_id"],)).fetchone()
            if outcome == "decline":
                conn.execute("UPDATE payments SET status = 'failed', failure_reason = %s, completed_at = now() "
                             "WHERE id = %s", ("Declined by payer", pay["id"]))
                notify.queue(conn, pay["user_id"], "payment_failed",
                             {"title": ev_row["title"], "reason": "declined by payer"})
            else:
                conn.execute("SAVEPOINT issue")
                try:
                    ev = _lock_event_for_sale(conn, pay["event_id"], pay["user_id"])
                    _issue_ticket(conn, ev, pay["user_id"], pay["id"])
                    conn.execute("UPDATE payments SET status = 'succeeded', completed_at = now() WHERE id = %s",
                                 (pay["id"],))
                    conn.execute("RELEASE SAVEPOINT issue")
                    event_id = ev["id"]
                except HTTPException as exc:
                    # Money arrived but no seat can be issued: undo the partial work, refund, tell the buyer.
                    conn.execute("ROLLBACK TO SAVEPOINT issue")
                    conn.execute("UPDATE payments SET status = 'refunded', failure_reason = %s, completed_at = now() "
                                 "WHERE id = %s", (f"{exc.detail}; refunded", pay["id"]))
                    notify.queue(conn, pay["user_id"], "payment_failed",
                                 {"title": ev_row["title"], "reason": f"{str(exc.detail).lower()}, refunded"})
    if event_id:
        publish_capacity(event_id)
    out = get_payment_out(public_id)
    out.pop("user_id", None)
    return out


@router.get("/payments/{public_id}")
def get_payment(public_id: str, user: dict = Depends(current_user)):
    out = get_payment_out(public_id)
    if out.pop("user_id") != user["id"]:
        raise HTTPException(404, "Payment not found")
    return out


@router.post("/payments/{public_id}/simulate")
def simulate(public_id: str, request: Request, user: dict = Depends(current_user)):
    if get_settings().is_production:
        raise HTTPException(404, "Not found")
    return finalize_payment(public_id, request.state.json["outcome"], user_id=user["id"])


@router.post("/payments/webhook")
async def webhook(request: Request):
    raw = await request.body()
    expected = hmac.new(get_settings().PAYMENT_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("x-signature", "")):
        raise HTTPException(401, "Invalid webhook signature")
    b = request.state.json
    return await run_in_threadpool(finalize_payment, b["payment_id"], b["outcome"])


@router.get("/tickets")
def my_tickets(user: dict = Depends(current_user)):
    return queries.user_tickets(user["id"])


@router.post("/tickets/{id}/cancel")
def cancel_ticket(id: int, user: dict = Depends(current_user)):
    with db.transaction() as conn:
        t = conn.execute("SELECT * FROM tickets WHERE id = %s FOR UPDATE", (id,)).fetchone()
        if t is None or t["user_id"] != user["id"]:
            raise HTTPException(404, "Ticket not found")
        if t["status"] != "confirmed":
            raise HTTPException(409, "Ticket is already cancelled")
        ev = conn.execute("SELECT * FROM events WHERE id = %s FOR UPDATE", (t["event_id"],)).fetchone()
        if ev["starts_at"] <= datetime.now(timezone.utc):
            raise HTTPException(409, "Tickets cannot be cancelled after the event starts")
        conn.execute("UPDATE tickets SET status = 'cancelled' WHERE id = %s", (id,))
        conn.execute("UPDATE events SET tickets_sold = tickets_sold - 1 WHERE id = %s", (ev["id"],))
        if t["payment_id"]:
            conn.execute("UPDATE payments SET status = 'refunded', completed_at = now() WHERE id = %s",
                         (t["payment_id"],))
    publish_capacity(ev["id"])
    return next(x for x in queries.user_tickets(user["id"]) if x["id"] == id)
