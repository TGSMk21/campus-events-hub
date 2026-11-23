import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import db
from ..security import (USER_COLUMNS, create_session, current_user, hash_password, public_user,
                        revoke_session, verify_password)

router = APIRouter(prefix="/api/v1", tags=["Auth"])


def body(request: Request) -> dict:
    return request.state.json                                   # set by ContractMiddleware after validation


@router.post("/auth/register", status_code=201)
def register(request: Request):
    b = body(request)
    try:
        u = db.fetch_one(f"""
            INSERT INTO users AS u (email, full_name, password_hash, role) VALUES (%s, %s, %s, %s)
            RETURNING {USER_COLUMNS}""",
            (b["email"].strip().lower(), b["full_name"].strip(), hash_password(b["password"]), b.get("role", "student")))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "An account with this email already exists")
    resp = JSONResponse(public_user(u), 201)
    create_session(resp, u["id"], request.headers.get("user-agent", ""))
    return resp


@router.post("/auth/login")
def login(request: Request):
    b = body(request)
    row = db.fetch_one(f"SELECT {USER_COLUMNS}, u.password_hash FROM users u WHERE u.email = %s",
                       (b["email"].strip().lower(),))
    if not verify_password(row["password_hash"] if row else None, b["password"]):
        raise HTTPException(401, "Invalid email or password")   # same answer for unknown email and wrong password
    db.execute("DELETE FROM sessions WHERE expires_at < now()")
    resp = JSONResponse(public_user(row))
    create_session(resp, row["id"], request.headers.get("user-agent", ""))   # fresh token: no session fixation
    return resp


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user: dict = Depends(current_user)):
    resp = Response(status_code=204)
    revoke_session(request, resp)
    return resp


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


@router.patch("/me")
def update_me(request: Request, user: dict = Depends(current_user)):
    b = body(request)
    phone = b["phone"] if "phone" in b else user["phone"]
    opt_in = b.get("whatsapp_opt_in", user["whatsapp_opt_in"])
    if opt_in and not phone:
        raise HTTPException(422, "Add a WhatsApp number before opting in to WhatsApp notifications")
    if phone:
        phone = phone if phone.startswith("+") else "+260" + phone[1:]
    u = db.fetch_one(f"""
        UPDATE users AS u SET full_name = %s, phone = %s, whatsapp_opt_in = %s, interests = %s
        WHERE id = %s RETURNING {USER_COLUMNS}""",
        (b.get("full_name", user["full_name"]).strip(), phone, opt_in and bool(phone),
         b.get("interests", user["interests"]), user["id"]))
    return public_user(u)
