"""Campus Event & Activities Hub: application factory."""
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from . import contract, db, notify
from .config import get_settings
from .middleware import ContractMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, problem
from .realtime import hub, router as ws_router
from .routes import admin, auth, bookings, events, groups, tickets

log = logging.getLogger("hub")
BASE = Path(__file__).parent


class CachedStatic(StaticFiles):
    """Lab 9: fingerprinted assets (?v=<hash>) are immutable for a year; un-fingerprinted ones revalidate."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            versioned = b"v=" in scope.get("query_string", b"")
            resp.headers["Cache-Control"] = ("public, max-age=31536000, immutable" if versioned
                                             else "public, max-age=300, must-revalidate")
        return resp


def asset_versions() -> dict[str, str]:
    root = BASE / "static"
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()[:10]
            for p in root.rglob("*") if p.is_file()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()                                              # fail fast on missing secrets
    await asyncio.to_thread(db.init_pool)
    hub.loop = asyncio.get_running_loop()
    tasks = [asyncio.create_task(hub.heartbeat())]
    if app.state.run_worker:
        tasks.append(asyncio.create_task(notify.worker()))
    yield
    for t in tasks:
        t.cancel()
    await asyncio.to_thread(db.close_pool)


def create_app(run_worker: bool = True) -> FastAPI:
    app = FastAPI(title="Campus Event & Activities Hub", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.run_worker = run_worker
    app.state.assets = asset_versions()

    # Middleware: the last one added runs first (outermost).
    app.add_middleware(ContractMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=600)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail, errs = exc.detail, None
        if isinstance(detail, dict):
            detail, errs = detail.get("detail", ""), detail.get("errors")
        if not request.url.path.startswith("/api/") and exc.status_code == 404:
            from .pages import render_error
            return render_error(request, 404, "Page not found", "That page doesn't exist or isn't visible to you.")
        return problem(exc.status_code, str(detail), errs, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errs = [{"field": "/" + "/".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return problem(422, "Request parameters are invalid", errs)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return problem(500, "Unexpected server error")         # never leak stack traces to clients

    @app.get("/openapi.json", include_in_schema=False)
    def openapi_json():
        return JSONResponse(contract.SPEC)

    @app.get("/api-docs", include_in_schema=False, response_class=HTMLResponse)
    def api_docs(request: Request):
        nonce = request.state.csp_nonce
        cdn = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14"
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API docs | Campus Event &amp; Activities Hub</title>
<link rel="stylesheet" href="{cdn}/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script nonce="{nonce}" src="{cdn}/swagger-ui-bundle.js" crossorigin="anonymous"></script>
<script nonce="{nonce}">window.ui = SwaggerUIBundle({{url: "/openapi.json", dom_id: "#swagger-ui",
  withCredentials: true, tryItOutEnabled: true, persistAuthorization: false}});</script></body></html>"""

    for r in (auth.router, events.router, tickets.router, groups.router, bookings.router, admin.router):
        app.include_router(r)
    app.include_router(ws_router)

    from .pages import router as pages_router
    app.include_router(pages_router)
    app.mount("/static", CachedStatic(directory=BASE / "static"), name="static")
    return app


app = create_app()
