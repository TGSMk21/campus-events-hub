from fastapi import APIRouter, Depends, HTTPException, Request

from .. import db, queries
from ..realtime import hub
from ..security import USER_COLUMNS, public_user, require_roles, revoke_all_sessions

router = APIRouter(prefix="/api/v1")


@router.get("/health", tags=["System"])
def health():
    try:
        db.fetch_one("SELECT 1")
        database = "up"
    except Exception:
        database = "down"
    stats = db.pool().get_stats()
    return {"status": "ok" if database == "up" else "degraded", "database": database,
            "pool": {k: stats.get(k, 0) for k in ("pool_min", "pool_max", "pool_size", "pool_available",
                                                   "requests_waiting", "requests_num", "connections_num")},
            "websocket_listeners": hub.count("live")}


@router.get("/admin/users", tags=["Admin"])
def users(request: Request, admin: dict = Depends(require_roles("admin"))):
    q = request.query_params.get("q") or ""
    rows = db.fetch_all(f"""SELECT {USER_COLUMNS} FROM users u
                            WHERE u.email ILIKE %s OR u.full_name ILIKE %s ORDER BY u.id LIMIT 100""",
                        (queries._like(q), queries._like(q)))
    return [public_user(r) for r in rows]


@router.patch("/admin/users/{id}", tags=["Admin"])
def update_user(id: int, request: Request, admin: dict = Depends(require_roles("admin"))):
    role = request.state.json["role"]
    if id == admin["id"] and role != "admin":
        raise HTTPException(422, "You cannot remove your own admin role")
    u = db.fetch_one(f"UPDATE users AS u SET role = %s WHERE id = %s RETURNING {USER_COLUMNS}", (role, id))
    if u is None:
        raise HTTPException(404, "User not found")
    if id != admin["id"]:
        revoke_all_sessions(id)                                 # privilege change -> force re-login
    return public_user(u)


@router.get("/admin/notifications", tags=["Admin"])
def notifications(admin: dict = Depends(require_roles("admin"))):
    return db.fetch_all("""
        SELECT n.id, u.email AS user_email, n.channel, n.template, n.status, n.attempts, n.last_error,
               n.created_at, n.sent_at
        FROM notifications n JOIN users u ON u.id = n.user_id ORDER BY n.id DESC LIMIT 100""")
