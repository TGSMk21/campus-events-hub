"""Venue booking review and approval documents (scope F-06, F-07)."""
import hashlib
import re
import secrets
from pathlib import Path

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .. import db, notify, queries
from ..config import get_settings
from ..realtime import hub, publish_venue
from ..security import can_manage, current_user, require_roles

router = APIRouter(prefix="/api/v1", tags=["Bookings"])

# File type is decided by magic bytes, never by the client's filename or Content-Type header.
MAGIC = [
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/msword", ".doc"),
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
]


def _when(b: dict) -> str:
    return b["starts_at"].astimezone(queries.LUSAKA).strftime("%a %d %b %Y, %H:%M")


@router.get("/bookings")
def list_bookings(request: Request, user: dict = Depends(require_roles("organizer", "admin"))):
    status = request.query_params.get("status") or None
    return queries.list_bookings(status, None if user["role"] == "admin" else user["id"])


@router.post("/bookings/{id}/approve")
def approve(id: int, request: Request, admin: dict = Depends(require_roles("admin"))):
    note = request.state.json.get("note") or None
    try:
        with db.transaction() as conn:
            b = conn.execute("""
                SELECT b.*, e.title, v.name AS venue_name FROM venue_bookings b
                JOIN events e ON e.id = b.event_id JOIN venues v ON v.id = b.venue_id
                WHERE b.id = %s FOR UPDATE OF b""", (id,)).fetchone()
            if b is None:
                raise HTTPException(404, "Booking not found")
            if b["status"] != "pending":
                raise HTTPException(409, f"Booking is already {b['status']}")
            # The EXCLUDE constraint no_double_booking raises here if an approved booking overlaps.
            conn.execute("""UPDATE venue_bookings SET status = 'approved', admin_note = %s, reviewed_by = %s,
                            reviewed_at = now() WHERE id = %s""", (note, admin["id"], id))
            conn.execute("UPDATE events SET status = 'published', updated_at = now() WHERE id = %s", (b["event_id"],))
            notify.queue(conn, b["requested_by"], "booking_approved",
                         {"title": b["title"], "venue": b["venue_name"], "when": _when(b)})
    except psycopg.errors.ExclusionViolation:
        clash = queries.get_booking(id)["conflicts"]
        approved = [c for c in clash if c["status"] == "approved"]
        name = approved[0]["event_title"] if approved else "another event"
        raise HTTPException(409, f"Venue already booked for an overlapping time by \"{name}\". Reject this request "
                                 "or ask the organizer to choose another time.")
    publish_venue(b["venue_id"], "booking_approved")
    hub.publish("live", {"type": "event_status", "event_id": b["event_id"], "status": "published"})
    return queries.get_booking(id)


@router.post("/bookings/{id}/reject")
def reject(id: int, request: Request, admin: dict = Depends(require_roles("admin"))):
    note = request.state.json["note"].strip()
    with db.transaction() as conn:
        b = conn.execute("SELECT b.*, e.title FROM venue_bookings b JOIN events e ON e.id = b.event_id "
                         "WHERE b.id = %s FOR UPDATE OF b", (id,)).fetchone()
        if b is None:
            raise HTTPException(404, "Booking not found")
        if b["status"] != "pending":
            raise HTTPException(409, f"Booking is already {b['status']}")
        conn.execute("""UPDATE venue_bookings SET status = 'rejected', admin_note = %s, reviewed_by = %s,
                        reviewed_at = now() WHERE id = %s""", (note, admin["id"], id))
        conn.execute("UPDATE events SET status = 'rejected', updated_at = now() WHERE id = %s", (b["event_id"],))
        notify.queue(conn, b["requested_by"], "booking_rejected", {"title": b["title"], "note": note})
    publish_venue(b["venue_id"], "booking_rejected")
    return queries.get_booking(id)


# --------------------------------------------------------------- documents --

def _owned_booking(id: int, user: dict) -> dict:
    b = db.fetch_one("SELECT id, requested_by FROM venue_bookings WHERE id = %s", (id,))
    if b is None or not can_manage(user, b["requested_by"]):
        raise HTTPException(404, "Booking not found")             # 404, not 403: don't confirm the id exists
    return b


def _safe_name(name: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name or "document").name)[:100].strip(" .") or "document"
    return stem if stem.lower().endswith(ext) else stem + ext


@router.get("/bookings/{id}/documents")
def list_documents(id: int, user: dict = Depends(current_user)):
    _owned_booking(id, user)
    return db.fetch_all("""
        SELECT d.id, d.filename, d.content_type, d.size_bytes, u.full_name AS uploaded_by_name, d.created_at
        FROM documents d JOIN users u ON u.id = d.uploaded_by WHERE d.booking_id = %s ORDER BY d.id""", (id,))


@router.post("/bookings/{id}/documents", status_code=201)
async def upload_document(id: int, file: UploadFile, user: dict = Depends(current_user)):
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(_owned_booking, id, user)
    s = get_settings()
    data = await file.read(s.MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(422, "The file is empty")
    if len(data) > s.MAX_UPLOAD_BYTES:
        raise HTTPException(422, f"Files must be {s.MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller")
    kind = next(((ct, ext) for magic, ct, ext in MAGIC if data.startswith(magic)), None)
    if kind is None:
        raise HTTPException(422, "Only PDF, DOC or DOCX files are accepted")
    content_type, ext = kind
    key = secrets.token_hex(16)
    folder = Path(s.UPLOAD_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / key).write_bytes(data)
    row = await run_in_threadpool(db.fetch_one, """
        INSERT INTO documents (booking_id, uploaded_by, filename, content_type, size_bytes, sha256, storage_key)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, filename, content_type, size_bytes, created_at""",
        (id, user["id"], _safe_name(file.filename, ext), content_type, len(data),
         hashlib.sha256(data).hexdigest(), key))
    return {**row, "uploaded_by_name": user["full_name"]}


@router.get("/documents/{id}")
def download_document(id: int, user: dict = Depends(current_user)):
    d = db.fetch_one("""SELECT d.*, b.requested_by FROM documents d JOIN venue_bookings b ON b.id = d.booking_id
                        WHERE d.id = %s""", (id,))
    if d is None or not can_manage(user, d["requested_by"]):
        raise HTTPException(404, "Document not found")
    path = Path(get_settings().UPLOAD_DIR) / d["storage_key"]   # storage_key is our random hex, never user input
    if not path.is_file():
        raise HTTPException(404, "Document file is missing")
    return FileResponse(path, media_type=d["content_type"], filename=d["filename"],
                        headers={"Cache-Control": "private, no-store"})
