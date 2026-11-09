"""Contract + security verification. Start app.py first, then:  python verify.py
Re-running within 60 s can trip the rate limiter; wait a minute or restart app.py."""
import json, socket, ssl
import httpx
from jsonschema import Draft202012Validator

SPEC = json.load(open("openapi.json"))
c = httpx.Client(base_url="https://localhost:8443", verify=False)
fails = 0


def deref(o):
    while "$ref" in o:
        node = SPEC
        for k in o["$ref"][2:].split("/"):
            node = node[k]
        o = node
    return o


def call(method, path, expect, **kw):
    """PASS only if status == expected, the status is documented in the spec, and the body matches the documented schema."""
    global fails
    r = c.request(method, path, **kw)
    doc = SPEC["paths"][path.split("?")[0]][method.lower()]["responses"].get(str(r.status_code))
    ok = r.status_code == expect and doc is not None
    if ok and r.content:
        schema = next(iter(deref(doc)["content"].values()))["schema"]
        ok = Draft202012Validator({**schema, "components": SPEC["components"]}).is_valid(r.json())
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {method} {path} -> {r.status_code} (expected {expect})")
    if r.status_code >= 400:
        print("      ", r.text)
    return r


good = {"username": "derrick", "email": "derrick@example.com", "password": "S3cure-pass!"}
print("== Lab 4: schema validation, RFC 7807 ==")
call("POST", "/api/v1/users", 201, json=good)
call("POST", "/api/v1/users", 422, json={**good, "role": "admin"})                        # unexpected property
call("POST", "/api/v1/users", 422, json={**good, "username": "a!", "password": "short"})  # pattern + minLength
call("POST", "/api/v1/users", 400, content="{bad json", headers={"content-type": "application/json"})
call("POST", "/api/v1/users?debug=1", 400, json=good)                                     # unexpected query parameter
call("POST", "/api/v1/users", 422, json=good)                                             # duplicate email

print("\n== Lab 5: sessions ==")
call("GET", "/api/v1/events", 401)                                                        # no session
call("POST", "/api/v1/auth/login", 401, json={"email": good["email"], "password": "wrong-password"})
r = call("POST", "/api/v1/auth/login", 200, json={"email": good["email"], "password": good["password"]})
cookie = r.headers["set-cookie"]
print("       Set-Cookie:", cookie)
flags = all(f in cookie for f in ("HttpOnly", "Secure", "SameSite=strict"))
print(f"{'PASS' if flags else 'FAIL'}  cookie has HttpOnly + Secure + SameSite")
fails += not flags
call("GET", "/api/v1/events", 200)
call("POST", "/api/v1/events", 201, json={"title": "Hackathon Night", "venue": "Main Hall", "date": "2026-11-20", "capacity": 150})
call("POST", "/api/v1/events", 422, json={"title": "Hackathon Night", "venue": "Main Hall", "date": "next friday", "capacity": 0})
sid = c.cookies["sid"]
call("POST", "/api/v1/auth/logout", 204)
print("       cookie jar after logout:", dict(c.cookies))
call("GET", "/api/v1/events", 401, headers={"Cookie": f"sid={sid}"})                      # replay the revoked token

print("\n== Lab 5: transport ==")
r = httpx.get("http://localhost:8080/api/v1/events", follow_redirects=False)
print("HTTP request   ->", r.status_code, r.headers.get("location"))
print("HSTS header    ->", c.get("/api-docs").headers.get("strict-transport-security"))


def tls(version):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    ctx.minimum_version = ctx.maximum_version = version
    with socket.create_connection(("localhost", 8443)) as s, ctx.wrap_socket(s, server_hostname="localhost") as t:
        return t.version(), t.cipher()[0]


print("TLS 1.3 client ->", tls(ssl.TLSVersion.TLSv1_3))
try:
    print("TLS 1.2 client ->", tls(ssl.TLSVersion.TLSv1_2), "<- FAIL, should be rejected")
    fails += 1
except ssl.SSLError as e:
    print("TLS 1.2 client -> rejected:", e.reason)

print("\n== Lab 4: rate limiting ==")
n = 0
while c.get("/api/v1/events").status_code != 429 and n < 100:
    n += 1
r = call("GET", "/api/v1/events", 429)
print("       headers:", {k: v for k, v in r.headers.items() if k.lower().startswith(("ratelimit", "retry"))})

print("\nRESULT:", "ALL CHECKS PASSED" if not fails else f"{fails} CHECK(S) FAILED")
