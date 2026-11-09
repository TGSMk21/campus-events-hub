"""ICT461 Labs 4 & 5 - one file: contract-driven validation, Swagger UI, rate limit, TLS 1.3, cookie sessions."""
import json, os, secrets, ssl, threading, time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer

import uvicorn
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from jsonschema import Draft202012Validator, FormatChecker
from starlette.exceptions import HTTPException

SPEC = json.load(open("openapi.json"))                      # the contract is the source of truth
app = FastAPI(docs_url="/api-docs", redoc_url=None)          # Swagger UI at /api-docs
app.openapi = lambda: SPEC                                   # serve the hand-written spec, not a generated one
LIMIT, WINDOW = int(os.getenv("RATE_LIMIT", 30)), 60         # requests per window (seconds) per IP
COOKIE = dict(key="sid", path="/", httponly=True, secure=True, samesite="strict")
users, sessions, events, hits, ph = {}, {}, {}, {}, PasswordHasher()   # in-memory stores; sessions: sid -> (user_id, expiry)

# One Draft 2020-12 validator per operation that declares a JSON request body
V = {(p, m): Draft202012Validator({**o["requestBody"]["content"]["application/json"]["schema"], "components": SPEC["components"]},
                                  format_checker=FormatChecker())
     for p, ms in SPEC["paths"].items() for m, o in ms.items() if "requestBody" in o}


def problem(status, detail, errors=None, headers=None):
    """RFC 7807 Problem Details response."""
    body = {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status, "detail": detail}
    return JSONResponse(body | ({"errors": errors} if errors else {}), status, headers, "application/problem+json")


async def gate(request: Request):
    """Enforce the spec before business logic: returns a Problem response, or None to let the request through."""
    path, method = request.url.path, request.method.lower()
    op = SPEC["paths"].get(path, {}).get(method)
    if not op:
        return None
    if request.query_params and not op.get("parameters"):
        return problem(400, "Unexpected query parameters")
    if op.get("security"):                                   # cookieAuth declared in the spec -> require a live session
        s = sessions.get(request.cookies.get("sid"))
        if not s or s[1] < time.time():
            return problem(401, "Missing, invalid or expired session")
        request.state.uid = s[0]
    if v := V.get((path, method)):
        try:
            data = json.loads(await request.body())
        except ValueError:
            return problem(400, "Request body is not valid JSON")
        errs = [{"field": "/" + "/".join(map(str, e.absolute_path)), "message": e.message} for e in v.iter_errors(data)]
        if errs:
            return problem(422, "Request body violates the schema", errs)


@app.middleware("http")
async def contract(request: Request, call_next):
    hdrs, resp = {}, None
    if request.url.path.startswith("/api/"):                 # fixed-window rate limit per client IP
        ip, now = request.client.host, time.time()
        if ip not in hits or now - hits[ip][0] >= WINDOW:
            hits[ip] = [now, 0]
        hits[ip][1] += 1
        reset = str(int(WINDOW - (now - hits[ip][0])) + 1)
        hdrs = {"RateLimit-Limit": str(LIMIT), "RateLimit-Remaining": str(max(0, LIMIT - hits[ip][1])), "RateLimit-Reset": reset}
        if hits[ip][1] > LIMIT:
            resp = problem(429, "Rate limit exceeded", headers={"Retry-After": reset})
    resp = resp or await gate(request) or await call_next(request)
    resp.headers.update(hdrs)
    resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


@app.exception_handler(HTTPException)                         # 404 / 405 also come back as Problem Details
async def http_error(request, exc):
    return problem(exc.status_code, str(exc.detail))


@app.exception_handler(Exception)
async def server_error(request, exc):
    return problem(500, "Unexpected server error")


def public(u):
    return {k: u[k] for k in ("id", "username", "email")}


@app.post("/api/v1/users", status_code=201)
async def create_user(request: Request):
    b = await request.json()
    if b["email"] in users:
        return problem(422, "Email already registered")
    users[b["email"]] = {"id": len(users) + 1, "username": b["username"], "email": b["email"], "hash": ph.hash(b["password"])}
    return public(users[b["email"]])


@app.post("/api/v1/auth/login")
async def login(request: Request):
    b = await request.json()
    try:
        ph.verify(users[b["email"]]["hash"], b["password"])
    except (KeyError, VerifyMismatchError):
        return problem(401, "Invalid credentials")            # same answer for unknown email and wrong password
    sid = secrets.token_urlsafe(32)                           # 256-bit CSPRNG token, new on every login
    sessions[sid] = (users[b["email"]]["id"], time.time() + 3600)
    r = JSONResponse(public(users[b["email"]]))
    r.set_cookie(value=sid, max_age=3600, **COOKIE)
    return r


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(request: Request):
    sessions.pop(request.cookies["sid"], None)                # revoke server-side first
    r = Response(status_code=204)
    r.delete_cookie(**COOKIE)                                 # then expire the client cookie
    return r


@app.get("/api/v1/events")
async def list_events(request: Request):
    return events.get(request.state.uid, [])


@app.post("/api/v1/events", status_code=201)
async def create_event(request: Request):
    o = {"id": sum(map(len, events.values())) + 1, **await request.json()}
    events.setdefault(request.state.uid, []).append(o)
    return o


if __name__ == "__main__":
    class Redirect(BaseHTTPRequestHandler):                   # plain-HTTP listener that only upgrades to HTTPS
        def do_GET(self):
            self.send_response(308)
            self.send_header("Location", f"https://localhost:8443{self.path}")
            self.end_headers()
        do_POST = do_PUT = do_DELETE = do_GET

    threading.Thread(target=HTTPServer(("", 8080), Redirect).serve_forever, daemon=True).start()
    cfg = uvicorn.Config(app, port=8443, ssl_keyfile="key.pem", ssl_certfile="cert.pem")
    cfg.load()
    cfg.ssl.minimum_version = ssl.TLSVersion.TLSv1_3          # TLS 1.3 only
    uvicorn.Server(cfg).run()
