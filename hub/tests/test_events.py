"""Scope F-02, F-03, F-05, F-06: events, search, venue conflicts, approval, recommendations, caching."""
from datetime import timedelta

from app import db

from .conftest import event_payload, future, published_event


def test_event_lifecycle_draft_submit_approve_publish(as_, anon, venue):
    org = as_("org")
    ev = org.post("/api/v1/events", json=event_payload(venue["id"])).json()
    assert ev["status"] == "draft"
    assert anon.get("/api/v1/events").json()["total"] == 0          # drafts are not public

    b = org.post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 80, "requirements": ["projector"]})
    assert b.status_code == 201, b.text
    assert b.json()["status"] == "pending"
    assert org.get(f"/api/v1/events/{ev['id']}").json()["status"] == "pending"
    assert org.patch(f"/api/v1/events/{ev['id']}", json={"title": "Changed title"}).status_code == 409

    r = as_("admin").post(f"/api/v1/bookings/{b.json()['id']}/approve", json={"note": "Enjoy"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    listed = anon.get("/api/v1/events").json()
    assert listed["total"] == 1 and listed["items"][0]["title"] == "Hackathon Night"
    templates = [n["template"] for n in db.fetch_all("SELECT template FROM notifications ORDER BY id")]
    assert templates == ["booking_submitted", "booking_approved"]


def test_reject_requires_note_and_allows_resubmission(as_, venue):
    org, admin = as_("org"), as_("admin")
    ev = org.post("/api/v1/events", json=event_payload(venue["id"])).json()
    b = org.post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 10}).json()
    assert admin.post(f"/api/v1/bookings/{b['id']}/reject", json={}).status_code == 422
    assert admin.post(f"/api/v1/bookings/{b['id']}/reject", json={"note": "Exam week, pick another date"}).status_code == 200
    assert org.get(f"/api/v1/events/{ev['id']}").json()["status"] == "rejected"
    later = future(10)
    assert org.patch(f"/api/v1/events/{ev['id']}", json={"starts_at": later.isoformat(),
                                                         "ends_at": (later + timedelta(hours=1)).isoformat()}).status_code == 200
    assert org.post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 10}).status_code == 201


def test_conflicts_reported_on_submit_and_double_booking_blocked(as_, venue):
    org, org2, admin = as_("org"), as_("org2"), as_("admin")
    a = org.post("/api/v1/events", json=event_payload(venue["id"], title="First booking")).json()
    starts = future()
    b = org2.post("/api/v1/events", json=event_payload(venue["id"], title="Overlapping booking",
                                                       starts=starts + timedelta(hours=1))).json()
    ba = org.post(f"/api/v1/events/{a['id']}/submit", json={"expected_attendance": 10}).json()
    bb = org2.post(f"/api/v1/events/{b['id']}/submit", json={"expected_attendance": 10}).json()
    assert [c["event_title"] for c in bb["conflicts"]] == ["First booking"]

    assert admin.post(f"/api/v1/bookings/{ba['id']}/approve", json={}).status_code == 200
    r = admin.post(f"/api/v1/bookings/{bb['id']}/approve", json={})
    assert r.status_code == 409 and "First booking" in r.json()["detail"]
    # The failed approval rolled back completely: booking still pending, event not published.
    assert db.fetch_one("SELECT status FROM venue_bookings WHERE id = %s", (bb["id"],))["status"] == "pending"
    assert db.fetch_one("SELECT status FROM events WHERE id = %s", (b["id"],))["status"] == "pending"
    assert db.fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE template = 'booking_approved'")["n"] == 1


def test_back_to_back_bookings_are_not_conflicts(as_, venue):
    org, admin = as_("org"), as_("admin")
    starts = future()
    a = org.post("/api/v1/events", json=event_payload(venue["id"], starts=starts)).json()
    b = org.post("/api/v1/events", json=event_payload(venue["id"], starts=starts + timedelta(hours=2))).json()
    ba = org.post(f"/api/v1/events/{a['id']}/submit", json={"expected_attendance": 5}).json()
    bb = org.post(f"/api/v1/events/{b['id']}/submit", json={"expected_attendance": 5}).json()
    assert bb["conflicts"] == []
    assert admin.post(f"/api/v1/bookings/{ba['id']}/approve", json={}).status_code == 200
    assert admin.post(f"/api/v1/bookings/{bb['id']}/approve", json={}).status_code == 200


def test_business_rules_beyond_the_schema(as_, venue):
    org = as_("org")
    r = org.post("/api/v1/events", json=event_payload(venue["id"], capacity=500))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "/capacity"
    starts = future()
    r = org.post("/api/v1/events", json={**event_payload(venue["id"]), "ends_at": (starts - timedelta(hours=1)).isoformat()})
    assert r.status_code == 422
    past = future(-2)
    assert org.post("/api/v1/events", json=event_payload(venue["id"], starts=past)).status_code == 422
    assert org.post("/api/v1/events", json=event_payload(9999)).status_code == 422
    ev = org.post("/api/v1/events", json=event_payload(venue["id"])).json()
    assert org.post(f"/api/v1/events/{ev['id']}/submit", json={"expected_attendance": 300}).status_code == 422


def test_search_and_filters(anon, users, venue):
    o = users["org"]["id"]
    published_event(o, venue["id"], title="Football Derby", category="sports")
    published_event(o, venue["id"], title="Careers Fair", category="career", price=1000, days=6)
    full = published_event(o, venue["id"], title="Full House Concert", category="cultural", capacity=1)
    db.execute("UPDATE events SET tickets_sold = 1 WHERE id = %s", (full["id"],))
    get = lambda **p: [e["title"] for e in anon.get("/api/v1/events", params=p).json()["items"]]  # noqa: E731
    assert get(q="derby") == ["Football Derby"]
    assert get(category="career") == ["Careers Fair"]
    assert get(free="true", available="true") == ["Football Derby"]
    assert "Full House Concert" not in get(available="true")
    d = (future(6)).date().isoformat()
    assert get(**{"from": d, "to": d}) == ["Careers Fair"]


def test_list_supports_etag_304(anon, users, venue):
    published_event(users["org"]["id"], venue["id"])
    r1 = anon.get("/api/v1/events")
    etag = r1.headers["etag"]
    assert "max-age" in r1.headers["cache-control"]
    r2 = anon.get("/api/v1/events", headers={"If-None-Match": etag})
    assert r2.status_code == 304 and r2.content == b""


def test_gzip_on_large_responses(anon, users, venue):
    for i in range(12):
        published_event(users["org"]["id"], venue["id"], title=f"Compressed event number {i}")
    r = anon.get("/api/v1/events", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_cancel_event_cancels_tickets_and_notifies(as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    for who in ("student", "student2"):
        assert as_(who).post(f"/api/v1/events/{ev['id']}/register").status_code == 201
    r = as_("org").post(f"/api/v1/events/{ev['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["tickets_sold"] == 0
    assert db.fetch_one("SELECT COUNT(*) AS n FROM tickets WHERE status = 'confirmed'")["n"] == 0
    assert db.fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE template = 'event_cancelled'")["n"] == 3  # 2 email + 1 WhatsApp


def test_recommendations_rank_followed_groups_and_interests(as_, users, venue):
    o = users["org"]["id"]
    g = db.fetch_one("INSERT INTO groups (slug, name, category) VALUES ('chess', 'Chess Club', 'club') RETURNING id")["id"]
    published_event(o, venue["id"], title="Random Talk", category="career", days=1)
    published_event(o, venue["id"], title="Chess Tournament", category="club", group_id=g, days=5)
    published_event(o, venue["id"], title="Football Match", category="sports", days=4)
    s = as_("student2")
    assert s.post("/api/v1/groups/chess/follow").status_code == 204
    s.patch("/api/v1/me", json={"interests": ["sports"]})
    recs = s.get("/api/v1/recommendations").json()
    assert [r["title"] for r in recs] == ["Chess Tournament", "Football Match", "Random Talk"]
    assert recs[0]["reasons"] == ["You follow Chess Club"]
    assert recs[1]["reasons"] == ["Matches your interest in sports"]
    assert recs[0]["score"] > recs[1]["score"] > recs[2]["score"]


def test_groups_and_venue_availability(as_, anon, users, venue):
    r = as_("org").post("/api/v1/groups", json={"slug": "robotics", "name": "Robotics Club", "category": "club"})
    assert r.status_code == 201
    assert as_("org").post("/api/v1/groups", json={"slug": "robotics", "name": "Dup", "category": "club"}).status_code == 409
    assert anon.get("/api/v1/groups/robotics").json()["followers"] == 0
    ev = published_event(users["org"]["id"], venue["id"])
    db.execute("""INSERT INTO venue_bookings (event_id, venue_id, requested_by, starts_at, ends_at, expected_attendance, status)
                  VALUES (%s, %s, %s, %s, %s, 10, 'approved')""",
               (ev["id"], venue["id"], users["org"]["id"], ev["starts_at"], ev["ends_at"]))
    slots = anon.get(f"/api/v1/venues/{venue['id']}/availability").json()["slots"]
    assert len(slots) == 1 and slots[0]["status"] == "approved"


def test_pages_render(as_, anon, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    for path in ("/", f"/events/{ev['id']}", "/groups", "/venues", "/help", "/login", "/register"):
        assert anon.get(path).status_code == 200, path
    assert anon.get("/account", follow_redirects=False).status_code == 303
    assert as_("student").get("/organizer").status_code == 403
    for path in ("/organizer", "/organizer/events/new", "/admin", "/account"):
        assert as_("admin").get(path).status_code == 200, path
    assert anon.get("/events/999999").status_code == 404
