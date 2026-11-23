"""The OpenAPI 3.1 contract for the Campus Event & Activities Hub API.

Contract-first (Lab 4): this document is written by hand and is the source of
truth. `ContractMiddleware` validates every JSON request body and query string
against it *before* a route handler runs, and the test-suite validates
responses against it. `scripts/export_openapi.py` writes it to openapi.json.
"""
import re
from typing import Any

CATEGORIES = ["academic", "club", "sports", "cultural", "career"]
REQUIREMENTS = ["projector", "sound", "seating"]
PHONE = r"^(\+260|0)[79][0-9]{8}$"


def ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def obj(props: dict, required: list[str] | None = None, *, closed: bool = True, **extra) -> dict:
    o: dict[str, Any] = {"type": "object", "properties": props, **extra}
    if required:
        o["required"] = required
    if closed:
        o["additionalProperties"] = False
    return o


STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}
DT = {"type": "string", "format": "date-time"}
ID = {"type": "integer", "minimum": 1}

SCHEMAS: dict[str, dict] = {
    "Problem": obj({
        "type": {"type": "string", "format": "uri-reference", "default": "about:blank"},
        "title": STR,
        "status": {"type": "integer", "minimum": 400, "maximum": 599},
        "detail": STR,
        "errors": {"type": "array", "items": obj({"field": STR, "message": STR}, ["field", "message"])},
    }, ["type", "title", "status"], description="RFC 7807 Problem Details, extended with a per-field errors array"),

    "Category": {"type": "string", "enum": CATEGORIES},
    "Role": {"type": "string", "enum": ["student", "organizer", "admin"]},

    # ---------- accounts ----------
    "RegisterRequest": obj({
        "email": {"type": "string", "format": "email", "maxLength": 254},
        "password": {"type": "string", "minLength": 10, "maxLength": 128,
                     "pattern": "^(?=.*[A-Za-z])(?=.*[0-9]).+$",
                     "description": "10-128 characters with at least one letter and one digit"},
        "full_name": {"type": "string", "minLength": 3, "maxLength": 60, "pattern": r"^[^<>]+$"},
        "role": {"type": "string", "enum": ["student", "organizer"], "default": "student"},
    }, ["email", "password", "full_name"]),
    "LoginRequest": obj({
        "email": {"type": "string", "format": "email", "maxLength": 254},
        "password": {"type": "string", "minLength": 1, "maxLength": 128},
    }, ["email", "password"]),
    "User": obj({
        "id": INT, "email": STR, "full_name": STR, "role": ref("Role"),
        "phone": nullable(STR), "whatsapp_opt_in": BOOL,
        "interests": {"type": "array", "items": ref("Category")},
    }, ["id", "email", "full_name", "role"]),
    "MeUpdate": obj({
        "full_name": {"type": "string", "minLength": 3, "maxLength": 60, "pattern": r"^[^<>]+$"},
        "phone": nullable({"type": "string", "pattern": PHONE}),
        "whatsapp_opt_in": BOOL,
        "interests": {"type": "array", "items": ref("Category"), "uniqueItems": True, "maxItems": 5},
    }, minProperties=1),

    # ---------- venues ----------
    "VenueRef": obj({"id": INT, "slug": STR, "name": STR}, ["id", "name"]),
    "Venue": obj({
        "id": INT, "slug": STR, "name": STR, "capacity": INT, "location": STR,
        "facilities": {"type": "array", "items": STR},
    }, ["id", "slug", "name", "capacity"]),
    "VenueCreate": obj({
        "slug": {"type": "string", "pattern": "^[a-z0-9-]{2,40}$"},
        "name": {"type": "string", "minLength": 3, "maxLength": 80},
        "capacity": {"type": "integer", "minimum": 1, "maximum": 5000},
        "location": {"type": "string", "maxLength": 120},
        "facilities": {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 10},
    }, ["slug", "name", "capacity"]),
    "Availability": obj({
        "venue": ref("Venue"),
        "slots": {"type": "array", "items": obj({
            "starts_at": DT, "ends_at": DT, "status": STR, "event_title": STR,
        }, ["starts_at", "ends_at", "status"])},
    }, ["venue", "slots"]),

    # ---------- groups ----------
    "Group": obj({
        "id": INT, "slug": STR, "name": STR, "category": STR, "description": STR,
        "meeting_info": STR, "contact_email": nullable(STR), "followers": INT,
        "following": BOOL, "upcoming_events": INT,
    }, ["id", "slug", "name", "category"]),
    "GroupCreate": obj({
        "slug": {"type": "string", "pattern": "^[a-z0-9-]{2,60}$"},
        "name": {"type": "string", "minLength": 3, "maxLength": 80, "pattern": r"^[^<>]+$"},
        "category": ref("Category"),
        "description": {"type": "string", "maxLength": 1000},
        "meeting_info": {"type": "string", "maxLength": 160},
        "contact_email": {"type": "string", "format": "email", "maxLength": 254},
    }, ["slug", "name", "category"]),

    # ---------- events ----------
    "EventCreate": obj({
        "title": {"type": "string", "minLength": 5, "maxLength": 80},
        "description": {"type": "string", "minLength": 20, "maxLength": 500},
        "category": ref("Category"),
        "venue_id": ID,
        "group_id": nullable(ID),
        "starts_at": DT,
        "ends_at": DT,
        "capacity": {"type": "integer", "minimum": 1, "maximum": 800},
        "price_ngwee": {"type": "integer", "minimum": 0, "maximum": 10_000_000,
                        "description": "Ticket price in ngwee (100 ngwee = K1). 0 means a free event."},
    }, ["title", "description", "category", "venue_id", "starts_at", "ends_at", "capacity"]),
    "EventUpdate": obj({
        "title": {"type": "string", "minLength": 5, "maxLength": 80},
        "description": {"type": "string", "minLength": 20, "maxLength": 500},
        "category": ref("Category"),
        "venue_id": ID,
        "group_id": nullable(ID),
        "starts_at": DT,
        "ends_at": DT,
        "capacity": {"type": "integer", "minimum": 1, "maximum": 800},
        "price_ngwee": {"type": "integer", "minimum": 0, "maximum": 10_000_000},
    }, minProperties=1),
    "Event": obj({
        "id": INT, "title": STR, "description": STR, "category": ref("Category"),
        "venue": ref("VenueRef"),
        "group": nullable(obj({"id": INT, "slug": STR, "name": STR}, ["id", "slug", "name"])),
        "organizer_name": STR, "organizer_id": INT,
        "starts_at": DT, "ends_at": DT,
        "capacity": INT, "tickets_sold": INT, "seats_left": INT, "price_ngwee": INT,
        "status": {"type": "string", "enum": ["draft", "pending", "published", "rejected", "cancelled"]},
        "booking_status": nullable(STR),
        "score": {"type": "number"},
        "reasons": {"type": "array", "items": STR},
    }, ["id", "title", "category", "venue", "starts_at", "ends_at", "capacity", "seats_left", "status"]),
    "EventPage": obj({
        "items": {"type": "array", "items": ref("Event")},
        "page": INT, "per_page": INT, "total": INT,
    }, ["items", "page", "per_page", "total"]),
    "Attendee": obj({"ticket_code": STR, "full_name": STR, "email": STR, "paid": BOOL, "created_at": DT},
                    ["ticket_code", "full_name"]),

    # ---------- bookings ----------
    "BookingSubmit": obj({
        "expected_attendance": {"type": "integer", "minimum": 1, "maximum": 800},
        "requirements": {"type": "array", "items": {"type": "string", "enum": REQUIREMENTS}, "uniqueItems": True},
    }, ["expected_attendance"]),
    "Conflict": obj({"booking_id": INT, "event_title": STR, "status": STR, "starts_at": DT, "ends_at": DT},
                    ["booking_id", "status", "starts_at", "ends_at"]),
    "Booking": obj({
        "id": INT, "event_id": INT, "event_title": STR, "venue": ref("VenueRef"),
        "requested_by_name": STR, "starts_at": DT, "ends_at": DT,
        "expected_attendance": INT, "requirements": {"type": "array", "items": STR},
        "status": {"type": "string", "enum": ["pending", "approved", "rejected", "cancelled"]},
        "admin_note": nullable(STR), "created_at": DT, "documents": INT,
        "conflicts": {"type": "array", "items": ref("Conflict")},
    }, ["id", "event_id", "status", "starts_at", "ends_at", "conflicts"]),
    "ReviewNote": obj({"note": {"type": "string", "maxLength": 300}}),
    "RejectNote": obj({"note": {"type": "string", "minLength": 5, "maxLength": 300}}, ["note"]),
    "Document": obj({
        "id": INT, "filename": STR, "content_type": STR, "size_bytes": INT,
        "uploaded_by_name": STR, "created_at": DT,
    }, ["id", "filename", "content_type", "size_bytes"]),

    # ---------- tickets & payments ----------
    "Ticket": obj({
        "id": INT, "code": STR, "status": STR, "paid": BOOL, "created_at": DT,
        "event": obj({"id": INT, "title": STR, "starts_at": DT, "venue_name": STR}, ["id", "title"]),
    }, ["id", "code", "status", "event"]),
    "Payment": obj({
        "public_id": STR, "status": {"type": "string", "enum": ["pending", "succeeded", "failed", "refunded"]},
        "amount_ngwee": INT, "event_id": INT, "event_title": STR,
        "failure_reason": nullable(STR), "ticket_code": nullable(STR), "pay_url": STR,
    }, ["public_id", "status", "amount_ngwee", "event_id"]),
    "PaymentSimulate": obj({"outcome": {"type": "string", "enum": ["success", "decline"]}}, ["outcome"]),
    "PaymentWebhook": obj({
        "payment_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{24}$"},
        "outcome": {"type": "string", "enum": ["success", "decline"]},
    }, ["payment_id", "outcome"]),

    # ---------- admin ----------
    "AdminUserUpdate": obj({"role": ref("Role")}, ["role"]),
    "Notification": obj({
        "id": INT, "user_email": STR, "channel": STR, "template": STR, "status": STR,
        "attempts": INT, "last_error": nullable(STR), "created_at": DT, "sent_at": nullable(DT),
    }, ["id", "channel", "template", "status"]),
    "Health": obj({"status": STR, "database": STR, "pool": {"type": "object"}}, ["status"], closed=False),
}

# ---------------------------------------------------------------- responses ---

RL_HEADERS = {
    "RateLimit-Limit": {"$ref": "#/components/headers/RateLimit-Limit"},
    "RateLimit-Remaining": {"$ref": "#/components/headers/RateLimit-Remaining"},
    "RateLimit-Reset": {"$ref": "#/components/headers/RateLimit-Reset"},
}


def problem_response(desc: str, extra_headers: dict | None = None) -> dict:
    r = {"description": desc, "content": {"application/problem+json": {"schema": ref("Problem")}}}
    if extra_headers:
        r["headers"] = extra_headers
    return r


RESPONSES = {
    "BadRequest": problem_response("Malformed JSON, unexpected query parameter or unsupported content type"),
    "Unauthorized": problem_response("Missing, invalid or expired session"),
    "Forbidden": problem_response("Authenticated, but the role or ownership check failed"),
    "NotFound": problem_response("Resource does not exist or is not visible to the caller"),
    "Conflict": problem_response("State conflict, e.g. venue already booked or event sold out"),
    "Unprocessable": problem_response("Request body violates the schema or a business rule"),
    "TooManyRequests": problem_response("Rate limit exceeded",
                                        {"Retry-After": {"$ref": "#/components/headers/Retry-After"}}),
    "ServerError": problem_response("Unexpected server error"),
}


def ok(desc: str, schema: dict | None = None, status: str = "200", headers: dict | None = None) -> dict:
    r: dict[str, Any] = {"description": desc, "headers": {**RL_HEADERS, **(headers or {})}}
    if schema is not None:
        r["content"] = {"application/json": {"schema": schema}}
    return {status: r}


def errors(*codes: int) -> dict:
    names = {400: "BadRequest", 401: "Unauthorized", 403: "Forbidden", 404: "NotFound",
             409: "Conflict", 422: "Unprocessable", 429: "TooManyRequests", 500: "ServerError"}
    base = {400, 429, 500}
    return {str(c): {"$ref": f"#/components/responses/{names[c]}"} for c in sorted(base | set(codes))}


def body(schema_name: str) -> dict:
    return {"required": True, "content": {"application/json": {"schema": ref(schema_name)}}}


def qp(name: str, schema: dict, desc: str = "") -> dict:
    return {"name": name, "in": "query", "required": False, "schema": schema, "description": desc}


def pp(name: str = "id", schema: dict | None = None) -> dict:
    return {"name": name, "in": "path", "required": True, "schema": schema or ID}


AUTH = [{"cookieAuth": []}]


def op(op_id: str, summary: str, tag: str, responses: dict, *, auth: bool = False, req: str | None = None,
       params: list | None = None, desc: str = "", roles: str = "") -> dict:
    o: dict[str, Any] = {"operationId": op_id, "summary": summary, "tags": [tag], "responses": responses}
    if desc or roles:
        o["description"] = (desc + (f"\n\n**Roles:** {roles}" if roles else "")).strip()
    if auth:
        o["security"] = AUTH
    if req:
        o["requestBody"] = body(req)
    if params:
        o["parameters"] = params
    return o


PAGING = [qp("page", {"type": "integer", "minimum": 1, "default": 1}),
          qp("per_page", {"type": "integer", "minimum": 1, "maximum": 50, "default": 12})]

PATHS: dict[str, dict] = {
    "/api/v1/health": {"get": op("health", "Liveness, database and pool status", "System",
                                 {**ok("Healthy", ref("Health")), **errors()})},

    # ----- auth -----
    "/api/v1/auth/register": {"post": op(
        "register", "Create a student or organizer account", "Auth",
        {**ok("Account created", ref("User"), "201"), **errors(409, 422)}, req="RegisterRequest",
        desc="Passwords are hashed with Argon2id. Admin accounts can only be granted by an admin.")},
    "/api/v1/auth/login": {"post": op(
        "login", "Start a session (sets the sid cookie)", "Auth",
        {**ok("Logged in", ref("User"), headers={"Set-Cookie": {
            "description": "sid=<256-bit random token>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=28800",
            "schema": STR}}), **errors(401, 422)},
        req="LoginRequest", desc="Stricter rate limit than other routes to slow down password guessing.")},
    "/api/v1/auth/logout": {"post": op(
        "logout", "Revoke the server-side session and expire the cookie", "Auth",
        {"204": {"description": "Session revoked"}, **errors(401)}, auth=True)},
    "/api/v1/me": {
        "get": op("getMe", "Current user profile", "Auth", {**ok("Profile", ref("User")), **errors(401)}, auth=True),
        "patch": op("updateMe", "Update profile, interests and WhatsApp consent", "Auth",
                    {**ok("Updated", ref("User")), **errors(401, 422)}, auth=True, req="MeUpdate"),
    },

    # ----- events -----
    "/api/v1/events": {
        "get": op("listEvents", "Search and filter published upcoming events", "Events",
                  {**ok("Page of events", ref("EventPage"), headers={"ETag": {"schema": STR}}), **errors()},
                  params=[qp("q", {"type": "string", "maxLength": 80}, "Text search in title and description"),
                          qp("category", ref("Category")),
                          qp("group", {"type": "string", "pattern": "^[a-z0-9-]{2,60}$"}, "Group slug"),
                          qp("venue", ID, "Venue id"),
                          qp("from", {"type": "string", "format": "date"}, "Earliest date (YYYY-MM-DD)"),
                          qp("to", {"type": "string", "format": "date"}, "Latest date (YYYY-MM-DD)"),
                          qp("available", {"type": "boolean"}, "Only events with seats left"),
                          qp("free", {"type": "boolean"}, "Only free events"),
                          *PAGING]),
        "post": op("createEvent", "Create a draft event", "Events",
                   {**ok("Draft created", ref("Event"), "201"), **errors(401, 403, 422)},
                   auth=True, req="EventCreate", roles="organizer, admin"),
    },
    "/api/v1/events/{id}": {
        "get": op("getEvent", "Event details", "Events", {**ok("Event", ref("Event")), **errors(404)},
                  params=[pp()], desc="Unpublished events are visible only to their organizer and admins."),
        "patch": op("updateEvent", "Edit a draft or rejected event", "Events",
                    {**ok("Updated", ref("Event")), **errors(401, 403, 404, 409, 422)},
                    auth=True, req="EventUpdate", params=[pp()], roles="owning organizer, admin"),
    },
    "/api/v1/events/{id}/submit": {"post": op(
        "submitEvent", "Request the venue and submit the event for approval", "Events",
        {**ok("Booking request created", ref("Booking"), "201"), **errors(401, 403, 404, 409, 422)},
        auth=True, req="BookingSubmit", params=[pp()], roles="owning organizer",
        desc="Returns any overlapping pending/approved bookings in `conflicts` so the organizer sees clashes early.")},
    "/api/v1/events/{id}/cancel": {"post": op(
        "cancelEvent", "Cancel an event and release its venue", "Events",
        {**ok("Cancelled", ref("Event")), **errors(401, 403, 404, 409)},
        auth=True, params=[pp()], roles="owning organizer, admin")},
    "/api/v1/events/{id}/attendees": {"get": op(
        "listAttendees", "Ticket holders for an event", "Events",
        {**ok("Attendees", {"type": "array", "items": ref("Attendee")}), **errors(401, 403, 404)},
        auth=True, params=[pp()], roles="owning organizer, admin")},
    "/api/v1/events/{id}/register": {"post": op(
        "registerForEvent", "Register for a free event (issues a ticket)", "Tickets",
        {**ok("Ticket issued", ref("Ticket"), "201"), **errors(401, 404, 409)}, auth=True, params=[pp()],
        desc="Runs in one transaction: lock the event row, check capacity, insert the ticket, "
             "increment tickets_sold and queue the email/WhatsApp notifications.")},
    "/api/v1/events/{id}/checkout": {"post": op(
        "checkout", "Start a simulated payment for a ticketed event", "Tickets",
        {**ok("Payment created", ref("Payment"), "201"), **errors(401, 404, 409)}, auth=True, params=[pp()])},
    "/api/v1/recommendations": {"get": op(
        "recommendations", "Personalised event feed", "Events",
        {**ok("Ranked events", {"type": "array", "items": ref("Event")}), **errors(401)}, auth=True,
        params=[qp("limit", {"type": "integer", "minimum": 1, "maximum": 20, "default": 6})],
        desc="Rule-based: followed groups (+3), declared interests (+2), categories of past tickets (+1), "
             "small boost for events that are filling up. No external AI service.")},
    "/api/v1/organizer/events": {"get": op(
        "myOrganizedEvents", "Events created by the caller, all statuses", "Events",
        {**ok("Events", {"type": "array", "items": ref("Event")}), **errors(401, 403)},
        auth=True, roles="organizer, admin")},

    # ----- groups -----
    "/api/v1/groups": {
        "get": op("listGroups", "Browse clubs and student groups", "Groups",
                  {**ok("Groups", {"type": "array", "items": ref("Group")}), **errors()},
                  params=[qp("q", {"type": "string", "maxLength": 80}), qp("category", ref("Category"))]),
        "post": op("createGroup", "Register a club or group", "Groups",
                   {**ok("Created", ref("Group"), "201"), **errors(401, 403, 409, 422)},
                   auth=True, req="GroupCreate", roles="organizer, admin"),
    },
    "/api/v1/groups/{slug}": {"get": op(
        "getGroup", "Group details", "Groups", {**ok("Group", ref("Group")), **errors(404)},
        params=[pp("slug", {"type": "string", "pattern": "^[a-z0-9-]{2,60}$"})])},
    "/api/v1/groups/{slug}/follow": {
        "post": op("followGroup", "Follow a group", "Groups", {"204": {"description": "Following"}, **errors(401, 404)},
                   auth=True, params=[pp("slug", {"type": "string", "pattern": "^[a-z0-9-]{2,60}$"})]),
        "delete": op("unfollowGroup", "Unfollow a group", "Groups", {"204": {"description": "Not following"},
                                                                     **errors(401, 404)},
                     auth=True, params=[pp("slug", {"type": "string", "pattern": "^[a-z0-9-]{2,60}$"})]),
    },

    # ----- venues -----
    "/api/v1/venues": {
        "get": op("listVenues", "Campus venues", "Venues",
                  {**ok("Venues", {"type": "array", "items": ref("Venue")}), **errors()}),
        "post": op("createVenue", "Add a venue", "Venues", {**ok("Created", ref("Venue"), "201"),
                                                             **errors(401, 403, 409, 422)},
                   auth=True, req="VenueCreate", roles="admin"),
    },
    "/api/v1/venues/{id}/availability": {"get": op(
        "venueAvailability", "Approved and pending bookings for a venue in a date range", "Venues",
        {**ok("Availability", ref("Availability")), **errors(404, 422)},
        params=[pp(), qp("from", {"type": "string", "format": "date"}),
                qp("to", {"type": "string", "format": "date"})])},

    # ----- bookings & documents -----
    "/api/v1/bookings": {"get": op(
        "listBookings", "Venue booking requests", "Bookings",
        {**ok("Bookings", {"type": "array", "items": ref("Booking")}), **errors(401, 403)}, auth=True,
        params=[qp("status", {"type": "string", "enum": ["pending", "approved", "rejected", "cancelled"]})],
        roles="admin (all), organizer (own)")},
    "/api/v1/bookings/{id}/approve": {"post": op(
        "approveBooking", "Approve a booking and publish the event", "Bookings",
        {**ok("Approved", ref("Booking")), **errors(401, 403, 404, 409, 422)},
        auth=True, req="ReviewNote", params=[pp()], roles="admin",
        desc="Fails with 409 if another approved booking overlaps; enforced by a PostgreSQL EXCLUDE constraint.")},
    "/api/v1/bookings/{id}/reject": {"post": op(
        "rejectBooking", "Reject a booking", "Bookings",
        {**ok("Rejected", ref("Booking")), **errors(401, 403, 404, 409, 422)},
        auth=True, req="RejectNote", params=[pp()], roles="admin")},
    "/api/v1/bookings/{id}/documents": {
        "get": op("listDocuments", "Approval documents attached to a booking", "Bookings",
                  {**ok("Documents", {"type": "array", "items": ref("Document")}), **errors(401, 404)},
                  auth=True, params=[pp()], roles="owning organizer, admin"),
        "post": {**op("uploadDocument", "Upload a PDF/DOC/DOCX approval document (max 5 MB)", "Bookings",
                      {**ok("Stored", ref("Document"), "201"), **errors(401, 404, 422)},
                      auth=True, params=[pp()], roles="owning organizer, admin",
                      desc="The file type is checked by its magic bytes, not the client-supplied name."),
                 "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": obj(
                     {"file": {"type": "string", "format": "binary"}}, ["file"])}}}},
    },
    "/api/v1/documents/{id}": {"get": op(
        "downloadDocument", "Download an approval document", "Bookings",
        {"200": {"description": "File", "content": {"application/octet-stream": {"schema": {
            "type": "string", "format": "binary"}}}}, **errors(401, 404)},
        auth=True, params=[pp()], roles="owning organizer, admin")},

    # ----- tickets & payments -----
    "/api/v1/tickets": {"get": op(
        "myTickets", "The caller's tickets", "Tickets",
        {**ok("Tickets", {"type": "array", "items": ref("Ticket")}), **errors(401)}, auth=True)},
    "/api/v1/tickets/{id}/cancel": {"post": op(
        "cancelTicket", "Cancel a ticket and release the seat", "Tickets",
        {**ok("Cancelled", ref("Ticket")), **errors(401, 404, 409)}, auth=True, params=[pp()])},
    "/api/v1/payments/{public_id}": {"get": op(
        "getPayment", "Payment status", "Tickets", {**ok("Payment", ref("Payment")), **errors(401, 404)},
        auth=True, params=[pp("public_id", {"type": "string", "pattern": "^[A-Za-z0-9_-]{24}$"})])},
    "/api/v1/payments/{public_id}/simulate": {"post": op(
        "simulatePayment", "Sandbox only: approve or decline a pending payment", "Tickets",
        {**ok("Final payment state", ref("Payment")), **errors(401, 404, 409, 422)},
        auth=True, req="PaymentSimulate",
        params=[pp("public_id", {"type": "string", "pattern": "^[A-Za-z0-9_-]{24}$"})],
        desc="Stands in for the mobile-money prompt of a real provider. No real money moves.")},
    "/api/v1/payments/webhook": {"post": {**op(
        "paymentWebhook", "Provider callback (HMAC-SHA256 signed)", "Tickets",
        {**ok("Processed", ref("Payment")), **errors(401, 404, 409, 422)}, req="PaymentWebhook",
        desc="The `X-Signature` header must be hex(HMAC-SHA256(PAYMENT_WEBHOOK_SECRET, raw body))."),
        "parameters": [{"name": "X-Signature", "in": "header", "required": True, "schema": STR}]}},

    # ----- admin -----
    "/api/v1/admin/users": {"get": op(
        "adminListUsers", "Search users", "Admin",
        {**ok("Users", {"type": "array", "items": ref("User")}), **errors(401, 403)}, auth=True,
        params=[qp("q", {"type": "string", "maxLength": 80})], roles="admin")},
    "/api/v1/admin/users/{id}": {"patch": op(
        "adminUpdateUser", "Change a user's role", "Admin",
        {**ok("Updated", ref("User")), **errors(401, 403, 404, 422)},
        auth=True, req="AdminUserUpdate", params=[pp()], roles="admin")},
    "/api/v1/admin/notifications": {"get": op(
        "adminNotifications", "Recent email/WhatsApp outbox entries", "Admin",
        {**ok("Notifications", {"type": "array", "items": ref("Notification")}), **errors(401, 403)},
        auth=True, roles="admin")},
}

SPEC: dict[str, Any] = {
    "openapi": "3.1.0",
    "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
    "info": {
        "title": "Campus Event & Activities Hub API",
        "version": "1.0.0",
        "description": (
            "ICT461 Group 2, Mulungushi University. Contract-first API: every request body and query string is "
            "validated against this document before it reaches business logic. Every `/api/` response carries "
            "`RateLimit-*` headers, and every error is RFC 7807 `application/problem+json`."),
    },
    "servers": [{"url": "https://localhost:8443"}],
    "tags": [{"name": t} for t in ["Auth", "Events", "Tickets", "Groups", "Venues", "Bookings", "Admin", "System"]],
    "paths": PATHS,
    "components": {
        "schemas": SCHEMAS,
        "responses": RESPONSES,
        "securitySchemes": {"cookieAuth": {"type": "apiKey", "in": "cookie", "name": "sid"}},
        "headers": {
            "RateLimit-Limit": {"description": "Requests allowed per window", "schema": INT},
            "RateLimit-Remaining": {"description": "Requests left in the current window", "schema": INT},
            "RateLimit-Reset": {"description": "Seconds until the window resets", "schema": INT},
            "Retry-After": {"description": "Seconds to wait before retrying", "schema": INT},
        },
    },
}

# ------------------------------------------------------------ path matching ---

_ROUTES: list[tuple[re.Pattern, str]] = []
for _tpl in PATHS:
    _rx = "^" + re.sub(r"\\\{([a-z_]+)\\\}", r"(?P<\1>[^/]+)", re.escape(_tpl)) + "$"
    _ROUTES.append((re.compile(_rx), _tpl))
# Literal paths must win over templated ones (/payments/webhook vs /payments/{public_id}).
_ROUTES.sort(key=lambda r: r[1].count("{"))


def match(path: str) -> str | None:
    for rx, tpl in _ROUTES:
        if rx.match(path):
            return tpl
    return None
