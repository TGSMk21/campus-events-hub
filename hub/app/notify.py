"""Email tickets and WhatsApp notifications via a transactional outbox.

Business code calls `queue(conn, ...)` *inside* its database transaction, so a
notification exists if and only if the change it describes was committed. A
background worker then claims queued rows with FOR UPDATE SKIP LOCKED and
delivers them.

Delivery uses real SMTP / the WhatsApp Cloud API only when credentials are
configured; otherwise the message is marked "simulated" and logged, which keeps
coursework testing away from real recipients.

SSRF (Lab 6, A10): the server never fetches a user-supplied URL. The only
outbound HTTP call goes through `_outbound()`, which allows HTTPS to a fixed
allow-list of hosts.
"""
import asyncio
import json
import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import urlsplit

import httpx
import psycopg

from . import db
from .config import get_settings

log = logging.getLogger("hub.notify")
ALLOWED_HOSTS = {"graph.facebook.com"}

TEMPLATES = {
    "ticket_confirmed": ("Your ticket for {title}",
                         "Hi {name}, your ticket for \"{title}\" on {when} at {venue} is confirmed. "
                         "Ticket code: {code}. Show this code at the entrance."),
    "booking_submitted": ("Venue request received: {title}",
                          "Hi {name}, your request for {venue} on {when} for \"{title}\" is pending admin review."),
    "booking_approved": ("Approved: {title}",
                         "Hi {name}, your booking for \"{title}\" at {venue} on {when} was approved. "
                         "The event is now published."),
    "booking_rejected": ("Not approved: {title}",
                         "Hi {name}, your booking for \"{title}\" was not approved. Note from the admin: {note}"),
    "event_cancelled": ("Cancelled: {title}",
                        "Hi {name}, \"{title}\" on {when} has been cancelled. Your ticket {code} is no longer valid."),
    "payment_failed": ("Payment not completed: {title}",
                       "Hi {name}, your payment for \"{title}\" did not go through ({reason}). No ticket was issued."),
}


def queue(conn: psycopg.Connection, user_id: int, template: str, data: dict) -> None:
    """Insert outbox rows on the caller's connection (and therefore in its transaction)."""
    if template not in TEMPLATES:
        raise ValueError(template)
    user = conn.execute("SELECT full_name, phone, whatsapp_opt_in FROM users WHERE id = %s", (user_id,)).fetchone()
    payload = json.dumps({"name": user["full_name"], **data}, default=str)
    conn.execute("INSERT INTO notifications (user_id, channel, template, payload) VALUES (%s, 'email', %s, %s)",
                 (user_id, template, payload))
    if user["whatsapp_opt_in"] and user["phone"]:                # explicit consent only
        conn.execute("INSERT INTO notifications (user_id, channel, template, payload) VALUES (%s, 'whatsapp', %s, %s)",
                     (user_id, template, payload))


def render(template: str, payload: dict) -> tuple[str, str]:
    subject, text = TEMPLATES[template]
    fields = {"note": "", "code": "", "reason": "", "venue": "", "when": "", **payload}
    return subject.format(**fields), text.format(**fields)


def _outbound(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"outbound request to {parts.hostname!r} is not allowed")
    return url


def _send_email(to: str, subject: str, text: str) -> str:
    s = get_settings()
    if not s.SMTP_HOST:
        log.info("[email:simulated] to=%s subject=%s", to, subject)
        return "simulated"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.SMTP_FROM, to, subject
    msg.set_content(text)
    with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=10) as smtp:
        smtp.starttls()
        if s.SMTP_USER:
            smtp.login(s.SMTP_USER, s.SMTP_PASSWORD)
        smtp.send_message(msg)
    return "sent"


def _send_whatsapp(phone: str, text: str) -> str:
    s = get_settings()
    if not (s.WHATSAPP_TOKEN and s.WHATSAPP_PHONE_NUMBER_ID):
        log.info("[whatsapp:simulated] to=%s text=%s", phone, text[:80])
        return "simulated"
    to = "260" + phone[-9:]                                     # E.164 without '+', Zambia
    url = _outbound(f"https://graph.facebook.com/v20.0/{s.WHATSAPP_PHONE_NUMBER_ID}/messages")
    r = httpx.post(url, timeout=10, follow_redirects=False,
                   headers={"Authorization": f"Bearer {s.WHATSAPP_TOKEN}"},
                   json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})
    r.raise_for_status()
    return "sent"


def deliver_batch(limit: int = 20) -> int:
    with db.transaction() as conn:
        rows = conn.execute("""
            UPDATE notifications n SET attempts = attempts + 1
            FROM users u
            WHERE n.user_id = u.id AND n.id IN (
                SELECT id FROM notifications WHERE status = 'queued' ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED)
            RETURNING n.id, n.channel, n.template, n.payload, n.attempts, u.email, u.phone, u.whatsapp_opt_in
        """, (limit,)).fetchall()
    for row in rows:
        try:
            subject, text = render(row["template"], row["payload"])
            if row["channel"] == "email":
                status = _send_email(row["email"], subject, text)
            elif row["whatsapp_opt_in"] and row["phone"]:
                status = _send_whatsapp(row["phone"], text)
            else:
                status = "skipped"                              # consent withdrawn after queueing
            db.execute("UPDATE notifications SET status = %s, sent_at = now(), last_error = NULL WHERE id = %s",
                       (status, row["id"]))
        except Exception as exc:                                 # keep the worker alive; retry up to 3 times
            final = row["attempts"] >= 3
            db.execute("UPDATE notifications SET status = %s, last_error = %s WHERE id = %s",
                       ("failed" if final else "queued", str(exc)[:300], row["id"]))
            log.warning("notification %s failed: %s", row["id"], exc)
    return len(rows)


async def worker(interval: float = 3.0) -> None:
    while True:
        try:
            while await asyncio.to_thread(deliver_batch) == 20:
                pass
        except Exception as exc:
            log.warning("outbox worker error: %s", exc)
        await asyncio.sleep(interval)
