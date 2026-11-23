"""Indexes for the hot query paths (Lab 7, Task 3).

Each index matches a WHERE / ORDER BY used by an endpoint:

* events_published_starts      -> public event list: WHERE status='published' AND starts_at >= now() ORDER BY starts_at
* events_category_starts       -> category filter on the same list
* events_organizer             -> organizer dashboard (foreign key)
* events_group                 -> group page (foreign key)
* bookings_venue_time          -> conflict check: venue_id = ? AND time range overlap
* bookings_status_created      -> admin queue: WHERE status='pending' ORDER BY created_at
* tickets_user                 -> "my tickets"
* notifications_queue          -> outbox worker: WHERE status='queued' ORDER BY id
* sessions_expires             -> expired-session sweep
* chat_event_id                -> chat history replay

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INDEXES = {
    "events_published_starts": "events (starts_at) WHERE status = 'published'",
    "events_category_starts": "events (category, starts_at) WHERE status = 'published'",
    "events_organizer": "events (organizer_id, starts_at DESC)",
    "events_group": "events (group_id)",
    "bookings_venue_time": "venue_bookings (venue_id, starts_at, ends_at)",
    "bookings_status_created": "venue_bookings (status, created_at)",
    "bookings_event": "venue_bookings (event_id)",
    "tickets_user": "tickets (user_id, created_at DESC)",
    "payments_user": "payments (user_id)",
    "notifications_queue": "notifications (id) WHERE status = 'queued'",
    "sessions_expires": "sessions (expires_at)",
    "sessions_user": "sessions (user_id)",
    "chat_event_id": "chat_messages (event_id, id DESC)",
    "documents_booking": "documents (booking_id)",
}


def upgrade() -> None:
    for name, definition in INDEXES.items():
        op.execute(f"CREATE INDEX {name} ON {definition}")


def downgrade() -> None:
    for name in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
