"""Lab 4: contract-first validation, RFC 7807 errors, rate limiting, response conformance."""
from jsonschema import Draft202012Validator

from app import contract
from app.middleware import limiter

from .conftest import event_payload


def schema_ok(schema_name: str, data) -> bool:
    v = Draft202012Validator({"$ref": f"#/components/schemas/{schema_name}", "components": contract.SPEC["components"]})
    errors = list(v.iter_errors(data))
    assert not errors, [e.message for e in errors]
    return True


def is_problem(r, status):
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert schema_ok("Problem", body)
    return body


def test_spec_is_openapi_31_and_served(anon):
    r = anon.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"] == "3.1.0"
    assert len(spec["paths"]) >= 25
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            assert "400" in op["responses"] and "429" in op["responses"] and "500" in op["responses"], (path, method)


def test_swagger_ui_mounted(anon):
    r = anon.get("/api-docs")
    assert r.status_code == 200 and "SwaggerUIBundle" in r.text
    nonce = r.headers["content-security-policy"].split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in r.text                          # inline bootstrapping allowed only via nonce


def test_unexpected_property_rejected_422(anon):
    body = is_problem(anon.post("/api/v1/auth/register", json={
        "email": "a@b.co", "password": "abcdefgh12", "full_name": "Alice", "role": "admin"}), 422)
    fields = {e["field"] for e in body["errors"]}
    assert "/role" in fields                                      # admin is not an allowed self-service role


def test_additional_properties_false(anon):
    body = is_problem(anon.post("/api/v1/auth/register", json={
        "email": "a@b.co", "password": "abcdefgh12", "full_name": "Alice", "is_admin": True}), 422)
    assert any("is_admin" in e["message"] for e in body["errors"])


def test_pattern_and_length_errors_listed_per_field(anon):
    body = is_problem(anon.post("/api/v1/auth/register", json={
        "email": "not-an-email", "password": "short", "full_name": "<b>"}), 422)
    fields = {e["field"] for e in body["errors"]}
    assert {"/email", "/password", "/full_name"} <= fields


def test_malformed_json_400(anon):
    is_problem(anon.post("/api/v1/auth/login", content=b"{bad json", headers={"content-type": "application/json"}), 400)


def test_wrong_content_type_415(anon):
    is_problem(anon.post("/api/v1/auth/login", content=b"email=a", headers={"content-type": "application/x-www-form-urlencoded"}), 415)


def test_unexpected_query_parameter_400(anon):
    body = is_problem(anon.get("/api/v1/events?debug=1"), 400)
    assert "debug" in body["detail"]


def test_query_parameter_type_checked_422(anon):
    is_problem(anon.get("/api/v1/events?per_page=500"), 422)
    is_problem(anon.get("/api/v1/events?category=gaming"), 422)


def test_unknown_route_is_problem_404(anon):
    is_problem(anon.get("/api/v1/nope"), 404)


def test_security_declared_routes_need_cookie(anon):
    is_problem(anon.get("/api/v1/tickets"), 401)


def test_responses_match_documented_schemas(as_, venue):
    org = as_("org")
    r = org.post("/api/v1/events", json=event_payload(venue["id"]))
    assert r.status_code == 201 and schema_ok("Event", r.json())
    assert schema_ok("User", org.get("/api/v1/me").json())
    assert schema_ok("EventPage", org.get("/api/v1/events").json())
    for v in org.get("/api/v1/venues").json():
        schema_ok("Venue", v)
    assert schema_ok("Health", org.get("/api/v1/health").json())


def test_rate_limit_429_with_headers(anon, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_PER_MINUTE", 3)
    limiter.reset()
    codes = [anon.get("/api/v1/venues") for _ in range(4)]
    assert [c.status_code for c in codes[:3]] == [200, 200, 200]
    assert codes[0].headers["RateLimit-Limit"] == "3" and codes[2].headers["RateLimit-Remaining"] == "0"
    body = is_problem(codes[3], 429)
    assert int(codes[3].headers["Retry-After"]) > 0 and "Rate limit" in body["detail"]


def test_login_has_stricter_limit(anon, users, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "LOGIN_RATE_LIMIT_PER_MINUTE", 2)
    limiter.reset()
    for _ in range(2):
        assert anon.post("/api/v1/auth/login", json={"email": "x@y.zz", "password": "nope"}).status_code == 401
    is_problem(anon.post("/api/v1/auth/login", json={"email": "x@y.zz", "password": "nope"}), 429)
    assert anon.get("/api/v1/venues").status_code == 200          # other routes use their own bucket
