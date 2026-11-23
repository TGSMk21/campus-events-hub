"""Test fixtures: a real PostgreSQL database (no mocks), migrated with Alembic, truncated between tests."""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/campus_hub_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-0123456789abcdef0123456789")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "test-webhook-secret-0123456789abcdef0123456789")
os.environ["ENV"] = "test"
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_ORIGIN"] = "https://testserver"
os.environ["UPLOAD_DIR"] = str(ROOT / ".pytest_uploads")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.middleware import limiter  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "Correct-horse-9"
TABLES = ("chat_messages, notifications, tickets, payments, documents, venue_bookings, events, venues, "
          "group_follows, groups, sessions, users")


@pytest.fixture(scope="session", autouse=True)
def migrated():
    env = {**os.environ}
    for cmd in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run([sys.executable, "-m", "alembic", *cmd], cwd=ROOT, env=env, check=True, capture_output=True)
    yield


@pytest.fixture(scope="session")
def app(migrated):
    application = create_app(run_worker=False)
    with TestClient(application, base_url="https://testserver"):   # runs lifespan once (pool, WS heartbeat)
        yield application


@pytest.fixture(autouse=True)
def clean(app):
    db.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    limiter.reset()
    yield


_PW_HASH = None


def make_user(email: str, role: str = "student", name: str | None = None, **extra) -> dict:
    global _PW_HASH
    _PW_HASH = _PW_HASH or hash_password(PASSWORD)              # Argon2 is slow on purpose; hash once
    return db.fetch_one(
        """INSERT INTO users (email, full_name, password_hash, role, phone, whatsapp_opt_in, interests)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (email, name or email.split("@")[0].title() + " User", _PW_HASH, role, extra.get("phone"),
         extra.get("whatsapp_opt_in", False), extra.get("interests", [])))


def client_for(app, email: str | None = None) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    if email:
        r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
    return c


@pytest.fixture
def anon(app):
    return client_for(app)


@pytest.fixture
def users():
    return {
        "admin": make_user("admin@mu.ac.zm", "admin"),
        "org": make_user("org@mu.ac.zm", "organizer"),
        "org2": make_user("org2@mu.ac.zm", "organizer"),
        "student": make_user("student@mu.ac.zm", "student", phone="+260971234567", whatsapp_opt_in=True),
        "student2": make_user("student2@mu.ac.zm", "student"),
    }


@pytest.fixture
def as_(app, users):
    cache: dict[str, TestClient] = {}

    def get(who: str) -> TestClient:
        if who not in cache:
            cache[who] = client_for(app, users[who]["email"])
        return cache[who]
    return get


@pytest.fixture
def venue():
    return db.fetch_one("INSERT INTO venues (slug, name, capacity) VALUES ('hall', 'Main Hall', 200) RETURNING *")


def future(days: int = 3, hour: int = 10) -> datetime:
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=days)
    return base.replace(hour=hour)


def event_payload(venue_id: int, **over) -> dict:
    starts = over.pop("starts", future())
    body = {"title": "Hackathon Night", "description": "Build something useful for campus life in teams.",
            "category": "academic", "venue_id": venue_id, "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(), "capacity": 100, "price_ngwee": 0}
    body.update(over)
    return body


def published_event(organizer_id: int, venue_id: int, capacity: int = 50, price: int = 0, days: int = 3,
                    group_id: int | None = None, category: str = "academic", title: str = "Published Event") -> dict:
    starts = future(days)
    return db.fetch_one(
        """INSERT INTO events (organizer_id, venue_id, group_id, title, description, category, starts_at, ends_at,
                               capacity, price_ngwee, status)
           VALUES (%s, %s, %s, %s, 'A published event description for tests.', %s, %s, %s, %s, %s, 'published')
           RETURNING *""",
        (organizer_id, venue_id, group_id, title, category, starts, starts + timedelta(hours=2), capacity, price))
