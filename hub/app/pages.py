"""Server-rendered HTML pages.

Rendering strategy (Lab 3): public discovery pages (events, groups, venues) are
server-rendered so content and SEO are present on first load and filters work
without JavaScript. Dashboards are rendered as shells and hydrated client-side
with fetch(). Jinja2 autoescaping HTML-encodes every user value.
"""
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import contract, db, queries
from .security import optional_user

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _when(d: datetime, fmt: str = "%a %d %b, %H:%M") -> str:
    return d.astimezone(queries.LUSAKA).strftime(fmt) if d else ""


def _money(ngwee: int) -> str:
    return "Free" if not ngwee else f"K{ngwee / 100:,.2f}"


templates.env.filters["when"] = _when
templates.env.filters["money"] = _money
templates.env.globals["CATEGORIES"] = contract.CATEGORIES
templates.env.globals["REQUIREMENTS"] = contract.REQUIREMENTS


def render(request: Request, name: str, user: dict | None, status: int = 200, **ctx) -> HTMLResponse:
    assets = request.app.state.assets

    def static(path: str) -> str:
        return f"/static/{path}?v={assets.get(path, '0')}"

    return templates.TemplateResponse(request, name, {
        "user": user, "nonce": request.state.csp_nonce, "static": static, "path": request.url.path, **ctx,
    }, status_code=status)


def render_error(request: Request, status: int, title: str, message: str) -> HTMLResponse:
    from .security import user_from_token, COOKIE_NAME
    return render(request, "error.html", user_from_token(request.cookies.get(COOKIE_NAME)), status,
                  title=title, message=message)


def _login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse("/login?" + urlencode({"next": request.url.path}), 303)


def _safe_next(value: str | None) -> str:
    # Open-redirect guard: only same-site relative paths.
    return value if value and value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"


def _int(v: str | None, default: int, lo: int = 1, hi: int = 10_000) -> int:
    try:
        return min(hi, max(lo, int(v)))
    except (TypeError, ValueError):
        return default


def _date(v: str | None) -> date | None:
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: dict | None = Depends(optional_user)):
    p = request.query_params
    filters = {
        "q": (p.get("q") or "")[:80], "category": p.get("category") if p.get("category") in contract.CATEGORIES else "",
        "from": p.get("from") or "", "to": p.get("to") or "", "available": p.get("available") == "1",
        "free": p.get("free") == "1",
    }
    page_no = _int(p.get("page"), 1)
    page = queries.search_events(q=filters["q"] or None, category=filters["category"] or None,
                                 date_from=_date(filters["from"]), date_to=_date(filters["to"]),
                                 available=filters["available"], free=filters["free"], page=page_no, per_page=12)
    filtering = any(filters.values())
    recs = queries.recommendations(user["id"], 3) if user and not filtering and page_no == 1 else []
    base_q = {k: ("1" if v is True else v) for k, v in filters.items() if v}
    pages = (page["total"] + 11) // 12
    return render(request, "index.html", user, page=page, filters=filters, recs=recs, filtering=filtering,
                  prev_url=("/?" + urlencode({**base_q, "page": page_no - 1})) if page_no > 1 else None,
                  next_url=("/?" + urlencode({**base_q, "page": page_no + 1})) if page_no < pages else None)


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_page(event_id: int, request: Request, user: dict | None = Depends(optional_user)):
    ev = queries.get_event(event_id)
    can_manage = bool(user and ev and (user["role"] == "admin" or user["id"] == ev["organizer_id"]))
    if ev is None or (ev["status"] != "published" and not can_manage):
        return render_error(request, 404, "Event not found", "This event doesn't exist or hasn't been published yet.")
    ticket = None
    if user:
        ticket = db.fetch_one("SELECT id, code FROM tickets WHERE event_id = %s AND user_id = %s AND status = 'confirmed'",
                              (event_id, user["id"]))
    return render(request, "event.html", user, ev=ev, ticket=ticket, can_manage=can_manage,
                  started=ev["starts_at"] <= datetime.now(timezone.utc))


@router.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request, user: dict | None = Depends(optional_user)):
    p = request.query_params
    q = (p.get("q") or "")[:80]
    cat = p.get("category") if p.get("category") in contract.CATEGORIES else ""
    return render(request, "groups.html", user, groups=queries.list_groups(user["id"] if user else None, q or None,
                                                                           cat or None), q=q, category=cat)


@router.get("/groups/{slug}", response_class=HTMLResponse)
def group_page(slug: str, request: Request, user: dict | None = Depends(optional_user)):
    g = queries.get_group(slug, user["id"] if user else None)
    if g is None:
        return render_error(request, 404, "Group not found", "We couldn't find that club or group.")
    return render(request, "group.html", user, group=g, events=queries.search_events(group=slug, per_page=50)["items"])


@router.get("/venues", response_class=HTMLResponse)
def venues_page(request: Request, user: dict | None = Depends(optional_user)):
    venues = queries.list_venues()
    selected = _int(request.query_params.get("venue"), venues[0]["id"] if venues else 0)
    venue = next((v for v in venues if v["id"] == selected), venues[0] if venues else None)
    start = _date(request.query_params.get("from")) or date.today()
    days = [start + timedelta(days=i) for i in range(14)]
    slots = queries.venue_slots(venue["id"], datetime.combine(start, time.min, queries.LUSAKA),
                                datetime.combine(start + timedelta(days=14), time.min, queries.LUSAKA)) if venue else []
    by_day: dict[date, list] = {d: [] for d in days}
    for s in slots:
        d = s["starts_at"].astimezone(queries.LUSAKA).date()
        by_day.setdefault(d, []).append(s)
    return render(request, "venues.html", user, venues=venues, venue=venue, days=days, by_day=by_day,
                  start=start, prev_from=(start - timedelta(days=14)).isoformat(),
                  next_from=(start + timedelta(days=14)).isoformat())


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: dict | None = Depends(optional_user)):
    nxt = _safe_next(request.query_params.get("next"))
    if user:
        return RedirectResponse(nxt, 303)
    return render(request, "login.html", None, next=nxt)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user: dict | None = Depends(optional_user)):
    if user:
        return RedirectResponse("/", 303)
    return render(request, "register.html", None, next=_safe_next(request.query_params.get("next")))


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request, user: dict | None = Depends(optional_user)):
    if not user:
        return _login_redirect(request)
    return render(request, "account.html", user, tickets=queries.user_tickets(user["id"]),
                  following=[g for g in queries.list_groups(user["id"]) if g["following"]])


@router.get("/organizer", response_class=HTMLResponse)
def organizer_page(request: Request, user: dict | None = Depends(optional_user)):
    if not user:
        return _login_redirect(request)
    if user["role"] not in ("organizer", "admin"):
        return render_error(request, 403, "Organizers only",
                            "Your account is a student account. Ask an administrator to give you organizer access.")
    return render(request, "organizer.html", user, events=queries.organizer_events(user["id"]),
                  bookings=queries.list_bookings(None, user["id"]))


@router.get("/organizer/events/new", response_class=HTMLResponse)
@router.get("/organizer/events/{event_id}/edit", response_class=HTMLResponse)
def event_form(request: Request, event_id: int | None = None, user: dict | None = Depends(optional_user)):
    if not user:
        return _login_redirect(request)
    if user["role"] not in ("organizer", "admin"):
        return render_error(request, 403, "Organizers only", "Only organizers can create events.")
    ev = queries.get_event(event_id) if event_id else None
    if event_id and (ev is None or (user["role"] != "admin" and ev["organizer_id"] != user["id"])):
        return render_error(request, 404, "Event not found", "We couldn't find that event.")
    return render(request, "event_form.html", user, ev=ev, venues=queries.list_venues(),
                  groups=queries.list_groups())


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: dict | None = Depends(optional_user)):
    if not user:
        return _login_redirect(request)
    if user["role"] != "admin":
        return render_error(request, 403, "Administrators only", "You don't have access to the admin console.")
    return render(request, "admin.html", user, pending=queries.list_bookings("pending", None),
                  recent=[b for b in queries.list_bookings(None, None) if b["status"] != "pending"][:15],
                  venues=queries.list_venues())


@router.get("/sandbox/pay/{public_id}", response_class=HTMLResponse)
def sandbox_pay(public_id: str, request: Request, user: dict | None = Depends(optional_user)):
    if not user:
        return _login_redirect(request)
    from .routes.tickets import get_payment_out
    try:
        pay = get_payment_out(public_id)
    except Exception:
        pay = None
    if pay is None or pay["user_id"] != user["id"]:
        return render_error(request, 404, "Payment not found", "This payment link is invalid.")
    return render(request, "sandbox_pay.html", user, pay=pay)


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request, user: dict | None = Depends(optional_user)):
    return render(request, "help.html", user)
