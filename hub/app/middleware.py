"""Pure-ASGI middleware stack.

Order (outermost first):
    SecurityHeadersMiddleware  -> CSP nonce + defence-in-depth headers on every response (Lab 6, Task 3)
    RateLimitMiddleware        -> fixed-window limit per client IP on /api/ (Lab 4, Task 4)
    ContractMiddleware         -> OpenAPI request validation, CSRF Origin check (Lab 4, Task 2)

Pure ASGI is used instead of BaseHTTPMiddleware so the request body can be
buffered, validated and replayed safely, and so WebSocket traffic passes through
untouched.
"""
import json
import secrets
import time
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qsl

from jsonschema import Draft202012Validator, FormatChecker
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from . import contract
from .config import get_settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def problem(status: int, detail: str, errors: list | None = None, headers: dict | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status,
                            "detail": detail}
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status, headers, media_type="application/problem+json")


# --------------------------------------------------------------- headers ----

class SecurityHeadersMiddleware:
    CDN = "https://cdn.jsdelivr.net"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        nonce = secrets.token_urlsafe(18)                       # 144-bit, fresh for every response
        scope.setdefault("state", {})["csp_nonce"] = nonce
        path: str = scope["path"]
        docs = path.startswith("/api-docs")

        script_src = f"'self' 'nonce-{nonce}'" + (f" {self.CDN}" if docs else "")
        style_src = "'self'" + (f" {self.CDN}" if docs else "")
        csp = "; ".join([
            "default-src 'self'",
            f"script-src {script_src}",
            f"style-src {style_src}",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ])

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["Content-Security-Policy"] = csp
                h["X-Content-Type-Options"] = "nosniff"
                h["Referrer-Policy"] = "strict-origin-when-cross-origin"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                h["Cross-Origin-Resource-Policy"] = "same-origin"
                h["X-Frame-Options"] = "DENY"
                h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
                h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
                if path.startswith("/api/") and "cache-control" not in h:
                    h["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ------------------------------------------------------------ rate limit ----

class RateLimiter:
    """Fixed window per (client IP, bucket). In-memory, so per process; a Redis
    counter would replace this when running several workers."""

    WINDOW = 60

    def __init__(self):
        self.hits: dict[tuple[str, str], list[float]] = {}

    def reset(self) -> None:
        self.hits.clear()

    def check(self, ip: str, bucket: str, limit: int) -> tuple[bool, dict[str, str]]:
        now = time.monotonic()
        if len(self.hits) > 10_000:                              # bound memory under IP churn
            self.hits = {k: v for k, v in self.hits.items() if now - v[0] < self.WINDOW}
        key = (ip, bucket)
        win = self.hits.get(key)
        if win is None or now - win[0] >= self.WINDOW:
            win = self.hits[key] = [now, 0]
        win[1] += 1
        reset = int(self.WINDOW - (now - win[0])) + 1
        headers = {"RateLimit-Limit": str(limit), "RateLimit-Remaining": str(max(0, limit - int(win[1]))),
                   "RateLimit-Reset": str(reset)}
        return win[1] <= limit, headers


limiter = RateLimiter()


class RateLimitMiddleware:
    STRICT = {"/api/v1/auth/login", "/api/v1/auth/register"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        s = get_settings()
        strict = scope["path"] in self.STRICT
        ip = (scope.get("client") or ("unknown", 0))[0]
        allowed, rl = limiter.check(ip, "auth" if strict else "api",
                                    s.LOGIN_RATE_LIMIT_PER_MINUTE if strict else s.RATE_LIMIT_PER_MINUTE)
        if not allowed:
            resp = problem(429, "Rate limit exceeded. Try again later.", headers={**rl, "Retry-After": rl["RateLimit-Reset"]})
            return await resp(scope, receive, send)

        async def send_with_rl(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(rl)
            await send(message)

        await self.app(scope, receive, send_with_rl)


# -------------------------------------------------------------- contract ----

def _validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator({**schema, "components": contract.SPEC["components"]},
                                format_checker=FormatChecker())


BODY_VALIDATORS: dict[tuple[str, str], Draft202012Validator] = {}
QUERY_SPECS: dict[tuple[str, str], tuple[dict[str, dict], Draft202012Validator]] = {}

for _path, _methods in contract.PATHS.items():
    for _method, _op in _methods.items():
        content = _op.get("requestBody", {}).get("content", {})
        if "application/json" in content:
            BODY_VALIDATORS[(_path, _method.upper())] = _validator(content["application/json"]["schema"])
        q = {p["name"]: p["schema"] for p in _op.get("parameters", []) if p["in"] == "query"}
        QUERY_SPECS[(_path, _method.upper())] = (
            q, _validator({"type": "object", "properties": q, "additionalProperties": False}))


def _resolve(schema: dict) -> dict:
    if "$ref" in schema:
        node: Any = contract.SPEC
        for part in schema["$ref"][2:].split("/"):
            node = node[part]
        return node
    return schema


def _coerce(value: str, schema: dict) -> Any:
    t = _resolve(schema).get("type")
    if t == "integer":
        try:
            return int(value)
        except ValueError:
            return value                                        # let the validator report the type error
    if t == "boolean":
        return {"true": True, "1": True, "false": False, "0": False}.get(value.lower(), value)
    return value


def _errors(validator: Draft202012Validator, data: Any, prefix: str = "") -> list[dict]:
    out = []
    for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        field = prefix + "/" + "/".join(map(str, e.absolute_path))
        msg = e.message
        if e.validator == "additionalProperties":
            msg = "Unexpected property: " + msg.split("(")[-1].rstrip(")").replace(" were unexpected", "").replace(" was unexpected", "")
        elif e.validator == "pattern" and "description" in e.schema:
            msg = e.schema["description"]
        out.append({"field": field, "message": msg})
    return out


class ContractMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        method = scope["method"]
        tpl = contract.match(scope["path"])
        operation = contract.PATHS.get(tpl, {}).get(method.lower()) if tpl else None
        if operation is None:
            return await self.app(scope, receive, send)          # router answers 404/405 as Problem Details

        headers = Headers(scope=scope)

        # CSRF defence in depth: SameSite=Strict already blocks cross-site cookies; also refuse a
        # state-changing request whose Origin is not this site.
        if method in UNSAFE and tpl != "/api/v1/payments/webhook":
            origin = headers.get("origin")
            if origin and origin not in _allowed_origins(scope, headers):
                return await problem(403, "Cross-origin request refused")(scope, receive, send)

        # Query string: no undeclared parameters, declared ones must match their schema.
        q_schemas, q_validator = QUERY_SPECS[(tpl, method)]
        pairs = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        unknown = sorted({k for k, _ in pairs if k not in q_schemas})
        if unknown:
            return await problem(400, "Unexpected query parameter(s): " + ", ".join(unknown))(scope, receive, send)
        query = {k: _coerce(v, q_schemas[k]) for k, v in pairs if v != ""}
        errs = _errors(q_validator, query, "query")
        if errs:
            return await problem(422, "Query parameters violate the contract", errs)(scope, receive, send)

        # Declared security: refuse early when there is no session cookie at all.
        # (The route dependency then checks the session is real and unexpired.)
        if operation.get("security") and "sid=" not in headers.get("cookie", ""):
            return await problem(401, "Authentication required")(scope, receive, send)

        validator = BODY_VALIDATORS.get((tpl, method))
        if validator is None:
            return await self.app(scope, receive, send)

        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return await problem(415 if ctype else 400, "Content-Type must be application/json")(scope, receive, send)

        raw = await _read_body(receive, limit=64 * 1024)
        if raw is None:
            return await problem(413, "Request body too large")(scope, receive, send)
        try:
            data = json.loads(raw or b"null")
        except (ValueError, UnicodeDecodeError):
            return await problem(400, "Request body is not valid JSON")(scope, receive, send)
        errs = _errors(validator, data)
        if errs:
            return await problem(422, "Request body violates the schema", errs)(scope, receive, send)

        scope.setdefault("state", {})["json"] = data
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _read_body(receive, limit: int) -> bytes | None:
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body"):
            break
    return b"".join(chunks)


def _allowed_origins(scope, headers: Headers) -> set[str]:
    host = headers.get("host", "")
    scheme = scope.get("scheme", "https")
    return {get_settings().PUBLIC_ORIGIN.rstrip("/"), f"{scheme}://{host}", f"https://{host}"}
