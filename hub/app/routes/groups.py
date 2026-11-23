from datetime import date, datetime, time, timedelta

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import db, queries
from ..security import current_user, optional_user, require_roles

router = APIRouter(prefix="/api/v1")


# ------------------------------------------------------------------ groups --

@router.get("/groups", tags=["Groups"])
def list_groups(request: Request, user: dict | None = Depends(optional_user)):
    p = request.query_params
    return queries.list_groups(user["id"] if user else None, p.get("q") or None, p.get("category") or None)


@router.get("/groups/{slug}", tags=["Groups"])
def get_group(slug: str, user: dict | None = Depends(optional_user)):
    g = queries.get_group(slug, user["id"] if user else None)
    if g is None:
        raise HTTPException(404, "Group not found")
    return g


@router.post("/groups", status_code=201, tags=["Groups"])
def create_group(request: Request, user: dict = Depends(require_roles("organizer", "admin"))):
    b = request.state.json
    try:
        db.execute("""
            INSERT INTO groups (slug, name, category, description, meeting_info, contact_email, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (b["slug"], b["name"].strip(), b["category"], b.get("description", "").strip(),
             b.get("meeting_info", "").strip(), b.get("contact_email"), user["id"]))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "A group with this slug already exists")
    return queries.get_group(b["slug"], user["id"])


def _group_id(slug: str) -> int:
    g = db.fetch_one("SELECT id FROM groups WHERE slug = %s", (slug,))
    if g is None:
        raise HTTPException(404, "Group not found")
    return g["id"]


@router.post("/groups/{slug}/follow", status_code=204, tags=["Groups"])
def follow(slug: str, user: dict = Depends(current_user)):
    db.execute("INSERT INTO group_follows (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
               (user["id"], _group_id(slug)))
    return Response(status_code=204)


@router.delete("/groups/{slug}/follow", status_code=204, tags=["Groups"])
def unfollow(slug: str, user: dict = Depends(current_user)):
    db.execute("DELETE FROM group_follows WHERE user_id = %s AND group_id = %s", (user["id"], _group_id(slug)))
    return Response(status_code=204)


# ------------------------------------------------------------------ venues --

@router.get("/venues", tags=["Venues"])
def list_venues():
    return queries.list_venues()


@router.post("/venues", status_code=201, tags=["Venues"])
def create_venue(request: Request, user: dict = Depends(require_roles("admin"))):
    b = request.state.json
    try:
        return db.fetch_one("""
            INSERT INTO venues (slug, name, capacity, location, facilities) VALUES (%s, %s, %s, %s, %s)
            RETURNING id, slug, name, capacity, location, facilities""",
            (b["slug"], b["name"].strip(), b["capacity"], b.get("location", ""), b.get("facilities", [])))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "A venue with this slug already exists")


@router.get("/venues/{id}/availability", tags=["Venues"])
def availability(id: int, request: Request):
    venue = db.fetch_one("SELECT id, slug, name, capacity, location, facilities FROM venues WHERE id = %s", (id,))
    if venue is None:
        raise HTTPException(404, "Venue not found")
    p = request.query_params
    start = date.fromisoformat(p["from"]) if p.get("from") else date.today()
    end = date.fromisoformat(p["to"]) if p.get("to") else start + timedelta(days=13)
    if end < start or (end - start).days > 62:
        raise HTTPException(422, "Choose a range of at most 62 days with 'to' on or after 'from'")
    slots = queries.venue_slots(id, datetime.combine(start, time.min, queries.LUSAKA),
                                datetime.combine(end + timedelta(days=1), time.min, queries.LUSAKA))
    return {"venue": venue, "slots": slots}
