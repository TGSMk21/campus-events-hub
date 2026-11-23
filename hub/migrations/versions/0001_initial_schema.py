"""Initial schema: users, sessions, groups, venues, events, bookings, documents,
payments, tickets, notifications outbox and chat.

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE users (
        id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        email           VARCHAR(254) NOT NULL UNIQUE CHECK (email = lower(email)),
        full_name       VARCHAR(60)  NOT NULL CHECK (char_length(full_name) >= 3),
        password_hash   TEXT         NOT NULL,
        role            VARCHAR(10)  NOT NULL DEFAULT 'student'
                        CHECK (role IN ('student', 'organizer', 'admin')),
        phone           VARCHAR(13),
        whatsapp_opt_in BOOLEAN      NOT NULL DEFAULT FALSE,
        interests       TEXT[]       NOT NULL DEFAULT '{}',
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CHECK (NOT whatsapp_opt_in OR phone IS NOT NULL)
    )""")

    op.execute("""
    CREATE TABLE sessions (
        token_hash  CHAR(64)    PRIMARY KEY,               -- SHA-256 of the cookie value; raw token never stored
        user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at  TIMESTAMPTZ NOT NULL,
        user_agent  VARCHAR(200)
    )""")

    op.execute("""
    CREATE TABLE groups (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        slug          VARCHAR(60)  NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]+$'),
        name          VARCHAR(80)  NOT NULL,
        category      VARCHAR(20)  NOT NULL,
        description   TEXT         NOT NULL DEFAULT '',
        contact_email VARCHAR(254),
        meeting_info  VARCHAR(160) NOT NULL DEFAULT '',
        created_by    BIGINT       REFERENCES users(id) ON DELETE SET NULL,
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
    )""")

    op.execute("""
    CREATE TABLE group_follows (
        user_id    BIGINT NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
        group_id   BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, group_id)
    )""")

    op.execute("""
    CREATE TABLE venues (
        id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        slug       VARCHAR(40) NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]+$'),
        name       VARCHAR(80) NOT NULL,
        capacity   INTEGER     NOT NULL CHECK (capacity > 0),
        location   VARCHAR(120) NOT NULL DEFAULT '',
        facilities TEXT[]      NOT NULL DEFAULT '{}',
        active     BOOLEAN     NOT NULL DEFAULT TRUE
    )""")

    op.execute("""
    CREATE TABLE events (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        organizer_id  BIGINT       NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        group_id      BIGINT       REFERENCES groups(id) ON DELETE SET NULL,
        venue_id      BIGINT       NOT NULL REFERENCES venues(id) ON DELETE RESTRICT,
        title         VARCHAR(80)  NOT NULL CHECK (char_length(title) >= 5),
        description   VARCHAR(500) NOT NULL CHECK (char_length(description) >= 20),
        category      VARCHAR(20)  NOT NULL
                      CHECK (category IN ('academic', 'club', 'sports', 'cultural', 'career')),
        starts_at     TIMESTAMPTZ  NOT NULL,
        ends_at       TIMESTAMPTZ  NOT NULL,
        capacity      INTEGER      NOT NULL CHECK (capacity BETWEEN 1 AND 800),
        price_ngwee   INTEGER      NOT NULL DEFAULT 0 CHECK (price_ngwee >= 0),   -- 100 ngwee = K1
        status        VARCHAR(10)  NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'pending', 'published', 'rejected', 'cancelled')),
        tickets_sold  INTEGER      NOT NULL DEFAULT 0,
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CHECK (ends_at > starts_at),
        CHECK (tickets_sold BETWEEN 0 AND capacity)          -- last line of defence against overselling
    )""")

    op.execute("""
    CREATE TABLE venue_bookings (
        id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_id            BIGINT      NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        venue_id            BIGINT      NOT NULL REFERENCES venues(id) ON DELETE RESTRICT,
        requested_by        BIGINT      NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        starts_at           TIMESTAMPTZ NOT NULL,
        ends_at             TIMESTAMPTZ NOT NULL,
        expected_attendance INTEGER     NOT NULL CHECK (expected_attendance > 0),
        requirements        TEXT[]      NOT NULL DEFAULT '{}',
        status              VARCHAR(10) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
        admin_note          VARCHAR(300),
        reviewed_by         BIGINT      REFERENCES users(id) ON DELETE SET NULL,
        reviewed_at         TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (ends_at > starts_at),
        -- The database itself refuses two APPROVED bookings that overlap in the same venue.
        -- The venue is expressed as a one-point range so both columns use core GiST range operators
        -- (no btree_gist extension needed). '[)' makes back-to-back bookings legal.
        CONSTRAINT no_double_booking EXCLUDE USING gist (
            int8range(venue_id, venue_id, '[]') WITH &&,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        ) WHERE (status = 'approved')
    )""")

    op.execute("""
    CREATE TABLE documents (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        booking_id    BIGINT       NOT NULL REFERENCES venue_bookings(id) ON DELETE CASCADE,
        uploaded_by   BIGINT       NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        filename      VARCHAR(120) NOT NULL,
        content_type  VARCHAR(80)  NOT NULL,
        size_bytes    INTEGER      NOT NULL CHECK (size_bytes > 0),
        sha256        CHAR(64)     NOT NULL,
        storage_key   CHAR(32)     NOT NULL UNIQUE,      -- random name on disk; user filename never used as a path
        created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
    )""")

    op.execute("""
    CREATE TABLE payments (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        public_id     CHAR(24)    NOT NULL UNIQUE,
        user_id       BIGINT      NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        event_id      BIGINT      NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
        amount_ngwee  INTEGER     NOT NULL CHECK (amount_ngwee > 0),
        provider      VARCHAR(20) NOT NULL DEFAULT 'sandbox',
        status        VARCHAR(10) NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded')),
        failure_reason VARCHAR(120),
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        completed_at  TIMESTAMPTZ
    )""")

    op.execute("""
    CREATE TABLE tickets (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        code          CHAR(12)    NOT NULL UNIQUE,
        event_id      BIGINT      NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
        user_id       BIGINT      NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        payment_id    BIGINT      REFERENCES payments(id) ON DELETE RESTRICT,
        status        VARCHAR(10) NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE UNIQUE INDEX one_live_ticket_per_user ON tickets (event_id, user_id) WHERE status = 'confirmed'")

    op.execute("""
    CREATE TABLE notifications (
        id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        channel     VARCHAR(10) NOT NULL CHECK (channel IN ('email', 'whatsapp')),
        template    VARCHAR(40) NOT NULL,
        payload     JSONB       NOT NULL DEFAULT '{}',
        status      VARCHAR(10) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'sent', 'simulated', 'failed', 'skipped')),
        attempts    SMALLINT    NOT NULL DEFAULT 0,
        last_error  VARCHAR(300),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        sent_at     TIMESTAMPTZ
    )""")

    op.execute("""
    CREATE TABLE chat_messages (
        id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_id    BIGINT       NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        user_id     BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body        VARCHAR(300) NOT NULL,
        created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
    )""")


def downgrade() -> None:
    for table in ("chat_messages", "notifications", "tickets", "payments", "documents",
                  "venue_bookings", "events", "venues", "group_follows", "groups", "sessions", "users"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
