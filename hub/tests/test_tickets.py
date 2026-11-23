"""Lab 7: ACID ticketing. Capacity under concurrency, rollback on failure, idempotent payments."""
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import db, notify
from app.config import get_settings

from .conftest import client_for, make_user, published_event


def test_free_registration_issues_ticket_and_queues_notifications(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    r = as_("student").post(f"/api/v1/events/{ev['id']}/register")
    assert r.status_code == 201, r.text
    t = r.json()
    assert len(t["code"]) == 12 and t["status"] == "confirmed" and t["paid"] is False
    assert db.fetch_one("SELECT tickets_sold FROM events WHERE id = %s", (ev["id"],))["tickets_sold"] == 1
    channels = sorted(n["channel"] for n in db.fetch_all("SELECT channel FROM notifications WHERE template = 'ticket_confirmed'"))
    assert channels == ["email", "whatsapp"]                      # student opted in to WhatsApp
    assert as_("student").post(f"/api/v1/events/{ev['id']}/register").status_code == 409   # one ticket per person


def test_no_whatsapp_without_consent(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    as_("student2").post(f"/api/v1/events/{ev['id']}/register")
    assert [n["channel"] for n in db.fetch_all("SELECT channel FROM notifications")] == ["email"]


def test_sold_out(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], capacity=1)
    assert as_("student").post(f"/api/v1/events/{ev['id']}/register").status_code == 201
    r = as_("student2").post(f"/api/v1/events/{ev['id']}/register")
    assert r.status_code == 409 and r.json()["detail"] == "Sold out"


def test_concurrent_buyers_never_oversell(app, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], capacity=5)
    buyers = [make_user(f"buyer{i}@mu.ac.zm") for i in range(20)]
    clients = [client_for(app, b["email"]) for b in buyers]

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda c: c.post(f"/api/v1/events/{ev['id']}/register").status_code, clients))

    assert codes.count(201) == 5 and codes.count(409) == 15
    row = db.fetch_one("SELECT tickets_sold, (SELECT COUNT(*) FROM tickets WHERE event_id = %s) AS n FROM events WHERE id = %s",
                       (ev["id"], ev["id"]))
    assert row["tickets_sold"] == row["n"] == 5


def test_failure_mid_transaction_rolls_everything_back(as_, users, venue, monkeypatch):
    ev = published_event(users["org"]["id"], venue["id"])

    def boom(*a, **k):
        raise RuntimeError("SMTP queue unavailable")
    monkeypatch.setattr(notify, "queue", boom)                    # fails AFTER ticket insert + counter update

    r = as_("student").post(f"/api/v1/events/{ev['id']}/register")
    assert r.status_code == 500 and "SMTP" not in r.text          # no internals leaked
    assert db.fetch_one("SELECT COUNT(*) AS n FROM tickets")["n"] == 0
    assert db.fetch_one("SELECT tickets_sold FROM events WHERE id = %s", (ev["id"],))["tickets_sold"] == 0


def test_database_check_constraint_is_last_line_of_defence(users, venue):
    ev = published_event(users["org"]["id"], venue["id"], capacity=2)
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE events SET tickets_sold = 3 WHERE id = %s", (ev["id"],))


def test_paid_checkout_success(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], price=2500)
    s = as_("student")
    assert s.post(f"/api/v1/events/{ev['id']}/register").status_code == 409    # paid events need checkout
    pay = s.post(f"/api/v1/events/{ev['id']}/checkout").json()
    assert pay["status"] == "pending" and pay["amount_ngwee"] == 2500 and pay["pay_url"].startswith("/sandbox/pay/")
    assert db.fetch_one("SELECT tickets_sold FROM events WHERE id = %s", (ev["id"],))["tickets_sold"] == 0
    done = s.post(f"/api/v1/payments/{pay['public_id']}/simulate", json={"outcome": "success"}).json()
    assert done["status"] == "succeeded" and len(done["ticket_code"]) == 12
    again = s.post(f"/api/v1/payments/{pay['public_id']}/simulate", json={"outcome": "decline"}).json()
    assert again["status"] == "succeeded"                         # idempotent: final state never changes
    assert s.get("/api/v1/tickets").json()[0]["paid"] is True


def test_paid_checkout_declined(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], price=2500)
    pay = as_("student").post(f"/api/v1/events/{ev['id']}/checkout").json()
    r = as_("student").post(f"/api/v1/payments/{pay['public_id']}/simulate", json={"outcome": "decline"}).json()
    assert r["status"] == "failed" and r["ticket_code"] is None
    assert db.fetch_one("SELECT COUNT(*) AS n FROM tickets")["n"] == 0
    assert db.fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE template = 'payment_failed'")["n"] >= 1


def test_paid_but_sold_out_meanwhile_is_refunded(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], price=1000, capacity=1)
    pay = as_("student").post(f"/api/v1/events/{ev['id']}/checkout").json()
    p2 = as_("student2").post(f"/api/v1/events/{ev['id']}/checkout").json()
    as_("student2").post(f"/api/v1/payments/{p2['public_id']}/simulate", json={"outcome": "success"})
    r = as_("student").post(f"/api/v1/payments/{pay['public_id']}/simulate", json={"outcome": "success"}).json()
    assert r["status"] == "refunded" and "Sold out" in r["failure_reason"]
    assert db.fetch_one("SELECT tickets_sold FROM events WHERE id = %s", (ev["id"],))["tickets_sold"] == 1


def _sign(body: bytes) -> str:
    return hmac.new(get_settings().PAYMENT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_requires_valid_hmac(as_, anon, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], price=1000)
    pay = as_("student").post(f"/api/v1/events/{ev['id']}/checkout").json()
    body = json.dumps({"payment_id": pay["public_id"], "outcome": "success"}).encode()
    hdr = {"content-type": "application/json"}
    assert anon.post("/api/v1/payments/webhook", content=body, headers={**hdr, "x-signature": "0" * 64}).status_code == 401
    r = anon.post("/api/v1/payments/webhook", content=body, headers={**hdr, "x-signature": _sign(body)})
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    r = anon.post("/api/v1/payments/webhook", content=body, headers={**hdr, "x-signature": _sign(body)})
    assert r.status_code == 200 and db.fetch_one("SELECT COUNT(*) AS n FROM tickets")["n"] == 1   # replay-safe


def test_cancel_ticket_releases_seat(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], capacity=1)
    t = as_("student").post(f"/api/v1/events/{ev['id']}/register").json()
    r = as_("student").post(f"/api/v1/tickets/{t['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert as_("student2").post(f"/api/v1/events/{ev['id']}/register").status_code == 201


def test_outbox_worker_delivers_in_simulation_mode(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    as_("student").post(f"/api/v1/events/{ev['id']}/register")
    assert notify.deliver_batch() == 2
    statuses = {n["channel"]: n["status"] for n in db.fetch_all("SELECT channel, status FROM notifications")}
    assert statuses == {"email": "simulated", "whatsapp": "simulated"}
    subject, text = notify.render("ticket_confirmed", {"name": "A", "title": "T", "code": "ABC", "when": "Mon", "venue": "Hall"})
    assert "ABC" in text and subject == "Your ticket for T"
