"""Lab 6: OWASP Top 10 checks: access control/IDOR, injection, XSS, CSP, CSRF, uploads, secrets."""
import pytest
from pydantic import ValidationError

from app import db

from .conftest import event_payload, published_event


# ---- A01 Broken access control / IDOR ----

def test_student_cannot_create_events(as_, venue):
    assert as_("student").post("/api/v1/events", json=event_payload(venue["id"])).status_code == 403


def test_organizer_cannot_edit_or_cancel_anothers_event(as_, venue):
    ev = as_("org").post("/api/v1/events", json=event_payload(venue["id"])).json()
    other = as_("org2")
    assert other.patch(f"/api/v1/events/{ev['id']}", json={"title": "Hijacked title"}).status_code == 404
    assert other.post(f"/api/v1/events/{ev['id']}/cancel").status_code == 404
    assert other.post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 10}).status_code == 404
    assert other.get(f"/api/v1/events/{ev['id']}/attendees").status_code == 404
    assert other.get(f"/api/v1/events/{ev['id']}").status_code == 404   # drafts are private


def test_admin_routes_forbidden_to_organizers(as_):
    assert as_("org").get("/api/v1/admin/users").status_code == 403
    assert as_("org").get("/api/v1/admin/notifications").status_code == 403


def test_only_admin_reviews_bookings(as_, venue):
    org = as_("org")
    ev = org.post("/api/v1/events", json=event_payload(venue["id"])).json()
    b = org.post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 50}).json()
    assert org.post(f"/api/v1/bookings/{b['id']}/approve", json={}).status_code == 403


def test_organizer_sees_only_own_bookings(as_, venue):
    for who in ("org", "org2"):
        ev = as_(who).post("/api/v1/events", json=event_payload(venue["id"], title=f"Event by {who}")).json()
        as_(who).post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 10})
    titles = [b["event_title"] for b in as_("org").get("/api/v1/bookings").json()]
    assert titles == ["Event by org"]
    assert len(as_("admin").get("/api/v1/bookings").json()) == 2


def test_tickets_and_payments_are_private(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], price=500)
    ticket = as_("student").post(f"/api/v1/events/{published_event(users['org']['id'], venue['id'])['id']}/register").json()
    pay = as_("student").post(f"/api/v1/events/{ev['id']}/checkout").json()
    thief = as_("student2")
    assert thief.post(f"/api/v1/tickets/{ticket['id']}/cancel").status_code == 404
    assert thief.get(f"/api/v1/payments/{pay['public_id']}").status_code == 404
    assert thief.post(f"/api/v1/payments/{pay['public_id']}/simulate", json={"outcome": "success"}).status_code == 404


# ---- A03 Injection ----

@pytest.mark.parametrize("payload", ["' OR 1=1 --", "%'; DROP TABLE users; --", "\\", "_%_"])
def test_search_is_parameterised(anon, users, venue, payload):
    published_event(users["org"]["id"], venue["id"])
    r = anon.get("/api/v1/events", params={"q": payload})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert db.fetch_one("SELECT COUNT(*) AS n FROM users")["n"] == 5


def test_sql_injection_in_login_email(anon, users):
    r = anon.post("/api/v1/auth/login", json={"email": "admin@mu.ac.zm' --", "password": "x"})
    assert r.status_code in (401, 422)


# ---- A03 XSS: stored payloads are rendered inert ----

def test_stored_xss_is_escaped_in_html(as_, anon, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    db.execute("UPDATE events SET title = %s, description = %s WHERE id = %s",
               ("<script>alert(1)</script>Club Night", '<img src=x onerror="alert(2)"> Come along for a fun night', ev["id"]))
    html = anon.get(f"/events/{ev['id']}").text
    assert "<script>alert(1)</script>" not in html and '<img src=x onerror' not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;Club Night" in html
    assert "&lt;img src=x onerror=" in html
    listing = anon.get("/").text
    assert "<script>alert(1)" not in listing


# ---- Lab 6 Task 3: CSP + headers ----

def test_csp_nonce_and_defence_headers(anon):
    r1, r2 = anon.get("/"), anon.get("/")
    csp = r1.headers["content-security-policy"]
    for d in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "base-uri 'none'"):
        assert d in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    n1 = csp.split("'nonce-")[1].split("'")[0]
    n2 = r2.headers["content-security-policy"].split("'nonce-")[1].split("'")[0]
    assert n1 != n2 and len(n1) >= 22
    assert r1.text.count(f'nonce="{n1}"') >= 2                    # every script tag carries this response's nonce
    assert "<script>" not in r1.text                              # no un-nonced inline scripts
    assert 'style="' not in r1.text                               # no inline styles (style-src 'self')
    h = r1.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert h["cross-origin-opener-policy"] == "same-origin"
    assert h["x-frame-options"] == "DENY"
    assert "max-age=63072000" in h["strict-transport-security"]


def test_api_responses_not_cached_by_default(as_):
    assert as_("student").get("/api/v1/me").headers["cache-control"] == "no-store"


# ---- CSRF: cross-origin state change refused ----

def test_cross_origin_post_refused(as_, venue):
    r = as_("org").post("/api/v1/events", json=event_payload(venue["id"]), headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = as_("org").post("/api/v1/events", json=event_payload(venue["id"]), headers={"Origin": "https://testserver"})
    assert ok.status_code == 201


def test_open_redirect_blocked(anon, users):
    r = anon.get("/login?next=//evil.example/phish", follow_redirects=False)
    assert 'data-next="/"' in r.text


# ---- Uploads: magic-byte validation and access control ----

def _booking(as_, venue):
    ev = as_("org").post("/api/v1/events", json=event_payload(venue["id"])).json()
    return as_("org").post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 20}).json()


def test_upload_accepts_real_pdf_and_restricts_download(as_, venue):
    b = _booking(as_, venue)
    pdf = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    r = as_("org").post(f"/api/v1/bookings/{b['id']}/documents", files={"file": ("../../etc/approval letter.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["filename"] == "approval letter.pdf" and doc["content_type"] == "application/pdf"
    assert as_("org").get(f"/api/v1/documents/{doc['id']}").content == pdf
    assert as_("admin").get(f"/api/v1/documents/{doc['id']}").status_code == 200
    assert as_("org2").get(f"/api/v1/documents/{doc['id']}").status_code == 404
    assert as_("student").get(f"/api/v1/documents/{doc['id']}").status_code == 404


def test_upload_rejects_disguised_html(as_, venue):
    b = _booking(as_, venue)
    r = as_("org").post(f"/api/v1/bookings/{b['id']}/documents",
                        files={"file": ("letter.pdf", b"<html><script>alert(1)</script></html>", "application/pdf")})
    assert r.status_code == 422


def test_upload_rejects_oversized(as_, venue, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_BYTES", 1000)
    b = _booking(as_, venue)
    r = as_("org").post(f"/api/v1/bookings/{b['id']}/documents", files={"file": ("big.pdf", b"%PDF-" + b"0" * 2000)})
    assert r.status_code == 422


# ---- A10 SSRF guard on the only outbound HTTP call ----

def test_outbound_allow_list():
    from app.notify import _outbound
    assert _outbound("https://graph.facebook.com/v20.0/1/messages")
    for bad in ("http://graph.facebook.com/x", "https://169.254.169.254/latest/meta-data", "https://localhost:5432",
                "https://graph.facebook.com.evil.example/x"):
        with pytest.raises(ValueError):
            _outbound(bad)


# ---- Lab 6 Task 4: fail fast on missing / weak secrets ----

def test_settings_refuse_missing_or_placeholder_secrets(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    monkeypatch.setenv("SESSION_SECRET", "change-me-to-a-long-random-string-at-least-32-chars")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    monkeypatch.setenv("SESSION_SECRET", "short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
