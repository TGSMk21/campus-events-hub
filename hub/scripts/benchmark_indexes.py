"""Lab 7, Task 3: EXPLAIN ANALYZE before and after the indexes.

Inserts a large synthetic data set into a *separate schema* (bench) so the real
tables are untouched, runs the three hottest queries without indexes, creates
the same indexes as migration 0002, and runs them again.

    python -m scripts.benchmark_indexes [--rows 200000]
"""
import argparse
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402

QUERIES = {
    "Public event list (status + date, sorted)": """
        SELECT id, title, starts_at FROM bench.events
        WHERE status = 'published' AND starts_at >= now() ORDER BY starts_at LIMIT 12""",
    "Category filter": """
        SELECT id, title, starts_at FROM bench.events
        WHERE status = 'published' AND category = 'sports' AND starts_at >= now() ORDER BY starts_at LIMIT 12""",
    "Venue conflict check": """
        SELECT id FROM bench.venue_bookings
        WHERE venue_id = 3 AND status IN ('pending', 'approved')
          AND starts_at < now() + interval '3 days 2 hours' AND ends_at > now() + interval '3 days'""",
    "Organizer dashboard (FK lookup)": """
        SELECT id, title FROM bench.events WHERE organizer_id = 42 ORDER BY starts_at DESC""",
}

INDEXES = [
    "CREATE INDEX ON bench.events (starts_at) WHERE status = 'published'",
    "CREATE INDEX ON bench.events (category, starts_at) WHERE status = 'published'",
    "CREATE INDEX ON bench.events (organizer_id, starts_at DESC)",
    "CREATE INDEX ON bench.venue_bookings (venue_id, starts_at, ends_at)",
]


def explain(conn, sql: str) -> tuple[float, str]:
    times, plan = [], ""
    for _ in range(5):
        rows = conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql).fetchall()
        text = "\n".join(r["QUERY PLAN"] for r in rows)
        times.append(float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1)))
        plan = text
    return statistics.median(times), plan


def node(plan: str) -> str:
    first = next(line for line in plan.splitlines() if "->" in line or "Scan" in line)
    m = re.search(r"(Seq Scan|Index Scan|Index Only Scan|Bitmap Heap Scan|Bitmap Index Scan)[^(]*", plan)
    return m.group(0).strip() if m else first.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=200_000)
    args = ap.parse_args()
    db.init_pool()
    with db.pool().connection() as conn:
        conn.execute("DROP SCHEMA IF EXISTS bench CASCADE")
        conn.execute("CREATE SCHEMA bench")
        conn.execute("""CREATE TABLE bench.events (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, organizer_id BIGINT,
                        title TEXT, category TEXT, status TEXT, starts_at TIMESTAMPTZ)""")
        conn.execute("""CREATE TABLE bench.venue_bookings (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, venue_id INT,
                        status TEXT, starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ)""")
        t0 = time.perf_counter()
        conn.execute("""
            INSERT INTO bench.events (organizer_id, title, category, status, starts_at)
            SELECT (random() * 500)::int, 'Event ' || g,
                   (ARRAY['academic','club','sports','cultural','career'])[1 + (random() * 4)::int],
                   (ARRAY['published','published','published','draft','cancelled','rejected'])[1 + (random() * 5)::int],
                   now() + (random() * 730 - 365) * interval '1 day'
            FROM generate_series(1, %s) g""", (args.rows,))
        conn.execute("""
            INSERT INTO bench.venue_bookings (venue_id, status, starts_at, ends_at)
            SELECT 1 + (random() * 20)::int, (ARRAY['approved','pending','rejected','cancelled'])[1 + (random() * 3)::int],
                   s, s + interval '2 hours'
            FROM (SELECT now() + (random() * 730 - 365) * interval '1 day' AS s FROM generate_series(1, %s)) x""",
                     (args.rows,))
        conn.execute("ANALYZE bench.events")
        conn.execute("ANALYZE bench.venue_bookings")
        print(f"Inserted {args.rows:,} events and {args.rows:,} bookings in {time.perf_counter() - t0:.1f}s\n")

        before = {name: explain(conn, sql) for name, sql in QUERIES.items()}
        for ddl in INDEXES:
            conn.execute(ddl)
        conn.execute("ANALYZE bench.events")
        conn.execute("ANALYZE bench.venue_bookings")
        after = {name: explain(conn, sql) for name, sql in QUERIES.items()}

        print(f"{'Query':42} {'Before (ms)':>12} {'After (ms)':>11} {'Speed-up':>9}")
        print("-" * 78)
        for name in QUERIES:
            b, a = before[name][0], after[name][0]
            print(f"{name:42} {b:12.3f} {a:11.3f} {b / max(a, 0.001):8.0f}x")
            print(f"    before: {node(before[name][1])}")
            print(f"    after:  {node(after[name][1])}")
        print("\nFull plan for the public event list AFTER indexing:\n")
        print(after["Public event list (status + date, sorted)"][1])
        conn.execute("DROP SCHEMA bench CASCADE")
    db.close_pool()


if __name__ == "__main__":
    main()
