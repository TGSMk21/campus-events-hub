"""Seed demo data: venues, users for each role, groups, events, bookings and tickets.

    python -m scripts.seed            # idempotent-ish: refuses if users already exist
    python -m scripts.seed --reset    # TRUNCATE everything first

Demo accounts (password for all: Campus-2026!):
    admin@mu.ac.zm      admin
    organizer@mu.ac.zm  organizer
    student@mu.ac.zm    student
"""
import argparse
import random
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.queries import LUSAKA  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "Campus-2026!"

VENUES = [
    ("auditorium", "Main Auditorium", 400, "Great East Road campus, Block A", ["projector", "sound", "stage"]),
    ("lecture-hall-a", "Lecture Hall A", 150, "School of Engineering & Technology", ["projector"]),
    ("sports-ground", "Sports Ground", 800, "Behind the student hostels", ["floodlights"]),
    ("student-centre", "Student Centre", 120, "Next to the main cafeteria", ["sound", "kitchen"]),
    ("ict-lab-3", "ICT Lab 3", 60, "School of Engineering & Technology, 2nd floor", ["computers", "projector"]),
]

GROUPS = [
    ("computer-science-society", "Computer Science Society", "academic",
     "Talks, hackathons and study sessions for anyone interested in software, data and systems.", "Thursdays 17:00, ICT Lab 3"),
    ("mu-football-club", "MU Football Club", "sports",
     "Men's and women's teams. Training is open to all skill levels; inter-university fixtures every month.", "Tue & Fri 16:00, Sports Ground"),
    ("drama-and-arts", "Drama & Arts Collective", "cultural",
     "Theatre, poetry and music nights. We stage two productions a year and run open-mic evenings.", "Wednesdays 18:00, Student Centre"),
    ("chess-club", "Chess Club", "club", "Casual games, puzzles and a termly tournament. Boards provided.", "Mondays 17:30, Library foyer"),
    ("careers-network", "Careers & Alumni Network", "career",
     "CV clinics, mock interviews and meet-the-employer sessions with alumni.", "Monthly, see events"),
    ("green-campus", "Green Campus Initiative", "club", "Tree planting, clean-ups and sustainability projects on campus.", "Saturdays 08:00"),
]

EVENTS = [  # (group slug, title, category, venue slug, days ahead, start hour, hours, capacity, price K, description)
    ("computer-science-society", "ICT461 Web Engineering Showcase", "academic", "auditorium", 3, 14, 3, 300, 0,
     "Student teams demo their web platforms: real-time apps, secure APIs and accessible interfaces. Judges from industry."),
    ("computer-science-society", "24-Hour Campus Hackathon", "academic", "ict-lab-3", 9, 9, 10, 60, 0,
     "Build something useful for campus life in teams of four. Food, mentors and prizes provided. Bring a laptop."),
    ("mu-football-club", "Inter-University Football Derby", "sports", "sports-ground", 5, 15, 2, 800, 10,
     "Mulungushi vs. Copperbelt University. Come in university colours. Gates open an hour before kick-off."),
    ("drama-and-arts", "Mr & Mrs IT Pageant", "cultural", "auditorium", 12, 18, 4, 350, 25,
     "The School of Technology's annual pageant: talent, fashion and a lot of laughter. Categories include coding and career."),
    ("drama-and-arts", "Open Mic Poetry Night", "cultural", "student-centre", 2, 18, 2, 100, 0,
     "Share a poem, a song or a story, or just come to listen. Sign-up sheet at the door from 17:30."),
    ("chess-club", "Termly Chess Tournament", "club", "student-centre", 7, 9, 6, 64, 5,
     "Swiss-system, 7 rounds, 15+10 time control. Beginners' section available. Trophies for the top three."),
    ("careers-network", "Tech Careers Fair 2026", "career", "auditorium", 15, 9, 6, 400, 0,
     "Meet employers from banking, telecoms and start-ups. Bring printed CVs; the CV clinic runs all morning."),
    ("careers-network", "CV & LinkedIn Clinic", "career", "lecture-hall-a", 4, 10, 2, 80, 0,
     "One-to-one CV reviews with alumni recruiters, plus a short talk on writing a LinkedIn profile that gets noticed."),
    ("green-campus", "Campus Tree Planting Day", "club", "sports-ground", 6, 8, 3, 200, 0,
     "We're planting 300 indigenous trees along the main road. Gloves and tools provided; wear clothes you can get dirty in."),
    (None, "Mental Health & Wellness Talk", "academic", "lecture-hall-a", 8, 16, 2, 150, 0,
     "The counselling unit on managing exam stress, sleep and burnout, with an anonymous Q&A at the end."),
]


def at(days: int, hour: int) -> datetime:
    d = datetime.now(LUSAKA).date() + timedelta(days=days)
    return datetime.combine(d, time(hour), LUSAKA)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    db.init_pool()
    if args.reset:
        db.execute("TRUNCATE chat_messages, notifications, tickets, payments, documents, venue_bookings, events, "
                   "venues, group_follows, groups, sessions, users RESTART IDENTITY CASCADE")
    elif db.fetch_one("SELECT 1 FROM users LIMIT 1"):
        sys.exit("Database already has users. Use --reset to wipe and reseed.")

    pw = hash_password(PASSWORD)
    with db.transaction() as conn:
        def user(email, name, role, interests=(), phone=None):
            return conn.execute("""INSERT INTO users (email, full_name, password_hash, role, interests, phone, whatsapp_opt_in)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                                (email, name, pw, role, list(interests), phone, phone is not None)).fetchone()["id"]

        admin = user("admin@mu.ac.zm", "Student Affairs Admin", "admin")
        org = user("organizer@mu.ac.zm", "Lushomo Lungo", "organizer", ["academic", "career"])
        org2 = user("drama@mu.ac.zm", "Racheal Sililo", "organizer", ["cultural"])
        student = user("student@mu.ac.zm", "Hamusonde Muntanga", "student", ["academic", "sports"], "+260971234567")
        others = [user(f"student{i}@mu.ac.zm", f"Demo Student {i}", "student",
                       random.sample(["academic", "club", "sports", "cultural", "career"], 2)) for i in range(1, 41)]

        venue_ids = {}
        for slug, name, cap, loc, fac in VENUES:
            venue_ids[slug] = conn.execute("INSERT INTO venues (slug, name, capacity, location, facilities) "
                                           "VALUES (%s, %s, %s, %s, %s) RETURNING id", (slug, name, cap, loc, fac)).fetchone()["id"]
        group_ids = {}
        for slug, name, cat, desc, meet in GROUPS:
            group_ids[slug] = conn.execute("""INSERT INTO groups (slug, name, category, description, meeting_info, contact_email, created_by)
                                              VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                                           (slug, name, cat, desc, meet, f"{slug}@mu.ac.zm", org)).fetchone()["id"]
        conn.execute("INSERT INTO group_follows (user_id, group_id) VALUES (%s, %s), (%s, %s)",
                     (student, group_ids["computer-science-society"], student, group_ids["mu-football-club"]))
        for u in others:
            for g in random.sample(list(group_ids.values()), 2):
                conn.execute("INSERT INTO group_follows (user_id, group_id) VALUES (%s, %s)", (u, g))

        rng = random.Random(461)
        for gslug, title, cat, vslug, days, hour, hours, cap, price, desc in EVENTS:
            owner = org2 if gslug == "drama-and-arts" else org
            starts, ends = at(days, hour), at(days, hour) + timedelta(hours=hours)
            eid = conn.execute("""INSERT INTO events (organizer_id, group_id, venue_id, title, description, category,
                                  starts_at, ends_at, capacity, price_ngwee, status)
                                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'published') RETURNING id""",
                               (owner, group_ids.get(gslug), venue_ids[vslug], title, desc, cat, starts, ends, cap,
                                price * 100)).fetchone()["id"]
            conn.execute("""INSERT INTO venue_bookings (event_id, venue_id, requested_by, starts_at, ends_at,
                            expected_attendance, requirements, status, reviewed_by, reviewed_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'approved', %s, now())""",
                         (eid, venue_ids[vslug], owner, starts, ends, cap, ["sound"], admin))
            sold = 0
            for u in rng.sample(others, rng.randint(3, 25)):
                conn.execute("INSERT INTO tickets (code, event_id, user_id) VALUES (%s, %s, %s)",
                             (f"SEED{eid:03d}{sold:05d}", eid, u))
                sold += 1
            conn.execute("UPDATE events SET tickets_sold = %s WHERE id = %s", (sold, eid))

        # A pending request that overlaps an approved booking, so the admin console shows a conflict.
        starts, ends = at(3, 15), at(3, 17)
        eid = conn.execute("""INSERT INTO events (organizer_id, group_id, venue_id, title, description, category,
                              starts_at, ends_at, capacity, status)
                              VALUES (%s, %s, %s, 'Chess Simul Exhibition', %s, 'club', %s, %s, 120, 'pending') RETURNING id""",
                           (org, group_ids["chess-club"], venue_ids["auditorium"],
                            "A grandmaster plays 30 students at once. Spectators welcome; players must register.",
                            starts, ends)).fetchone()["id"]
        conn.execute("""INSERT INTO venue_bookings (event_id, venue_id, requested_by, starts_at, ends_at, expected_attendance, requirements)
                        VALUES (%s, %s, %s, %s, %s, 120, %s)""", (eid, venue_ids["auditorium"], org, starts, ends, ["projector"]))
        # A pending request with no conflict.
        starts, ends = at(20, 10), at(20, 13)
        eid = conn.execute("""INSERT INTO events (organizer_id, group_id, venue_id, title, description, category,
                              starts_at, ends_at, capacity, status)
                              VALUES (%s, %s, %s, 'Intro to Git & GitHub Workshop', %s, 'academic', %s, %s, 60, 'pending') RETURNING id""",
                           (org, group_ids["computer-science-society"], venue_ids["ict-lab-3"],
                            "Hands-on: branches, pull requests and resolving merge conflicts. Bring a laptop with Git installed.",
                            starts, ends)).fetchone()["id"]
        conn.execute("""INSERT INTO venue_bookings (event_id, venue_id, requested_by, starts_at, ends_at, expected_attendance, requirements)
                        VALUES (%s, %s, %s, %s, %s, 50, %s)""", (eid, venue_ids["ict-lab-3"], org, starts, ends, ["projector"]))
        # A draft.
        conn.execute("""INSERT INTO events (organizer_id, venue_id, title, description, category, starts_at, ends_at, capacity)
                        VALUES (%s, %s, 'Robotics Club Launch', %s, 'club', %s, %s, 100)""",
                     (org, venue_ids["lecture-hall-a"], "Meet the team building our entry for the national robotics challenge.",
                      at(25, 14), at(25, 16)))
    print(f"Seeded. Sign in with admin@mu.ac.zm / organizer@mu.ac.zm / student@mu.ac.zm, password {PASSWORD}")
    db.close_pool()


if __name__ == "__main__":
    main()
