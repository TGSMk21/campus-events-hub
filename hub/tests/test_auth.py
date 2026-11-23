"""Lab 5: Argon2 hashing, hardened session cookies, revocation, role-change sign-out."""
import hashlib

from app import db

from .conftest import PASSWORD, client_for


def test_register_sets_hardened_cookie_and_hashes_password(anon):
    r = anon.post("/api/v1/auth/register", json={"email": "New@Mu.ac.zm", "password": "abcdefgh12", "full_name": "New Person"})
    assert r.status_code == 201
    assert r.json()["email"] == "new@mu.ac.zm" and r.json()["role"] == "student"
    cookie = r.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag.lower() in cookie.lower(), cookie
    row = db.fetch_one("SELECT password_hash FROM users WHERE email = 'new@mu.ac.zm'")
    assert row["password_hash"].startswith("$argon2id$")


def test_duplicate_email_409(anon, users):
    r = anon.post("/api/v1/auth/register", json={"email": "student@mu.ac.zm", "password": "abcdefgh12", "full_name": "Dup"})
    assert r.status_code == 409


def test_login_failures_are_indistinguishable(anon, users):
    wrong_pw = anon.post("/api/v1/auth/login", json={"email": "student@mu.ac.zm", "password": "wrong-password1"})
    no_user = anon.post("/api/v1/auth/login", json={"email": "ghost@mu.ac.zm", "password": "wrong-password1"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["detail"] == no_user.json()["detail"]


def test_only_token_hash_is_stored(app, users):
    c = client_for(app, "student@mu.ac.zm")
    token = c.cookies["sid"]
    assert len(token) >= 43                                       # 32 random bytes, base64url
    stored = db.fetch_one("SELECT token_hash FROM sessions")["token_hash"]
    assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in stored


def test_each_login_issues_a_fresh_token(app, users):
    a = client_for(app, "student@mu.ac.zm").cookies["sid"]
    b = client_for(app, "student@mu.ac.zm").cookies["sid"]
    assert a != b


def test_logout_revokes_server_side_and_clears_cookie(app, users):
    c = client_for(app, "student@mu.ac.zm")
    token = c.cookies["sid"]
    assert c.get("/api/v1/me").status_code == 200
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower() or "expires=" in r.headers["set-cookie"].lower()
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sessions")["n"] == 0
    replay = client_for(app)
    replay.cookies.set("sid", token, domain="testserver.local")
    assert replay.get("/api/v1/me", headers={"cookie": f"sid={token}"}).status_code == 401


def test_expired_session_rejected(app, users):
    c = client_for(app, "student@mu.ac.zm")
    db.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert c.get("/api/v1/me").status_code == 401


def test_forged_token_rejected(anon):
    assert anon.get("/api/v1/me", headers={"cookie": "sid=" + "A" * 43}).status_code == 401


def test_profile_update_and_whatsapp_consent_rules(as_):
    s = as_("student2")
    r = s.patch("/api/v1/me", json={"whatsapp_opt_in": True})
    assert r.status_code == 422                                   # no phone yet
    r = s.patch("/api/v1/me", json={"phone": "0961234567", "whatsapp_opt_in": True, "interests": ["sports", "career"]})
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "+260961234567" and r.json()["whatsapp_opt_in"] is True
    assert s.patch("/api/v1/me", json={"phone": "12345"}).status_code == 422


def test_role_change_signs_user_out(as_, users):
    student = as_("student2")
    assert student.get("/api/v1/me").status_code == 200
    r = as_("admin").patch(f"/api/v1/admin/users/{users['student2']['id']}", json={"role": "organizer"})
    assert r.status_code == 200 and r.json()["role"] == "organizer"
    assert student.get("/api/v1/me").status_code == 401


def test_admin_cannot_demote_self(as_, users):
    assert as_("admin").patch(f"/api/v1/admin/users/{users['admin']['id']}", json={"role": "student"}).status_code == 422


def test_password_not_in_any_response(anon):
    r = anon.post("/api/v1/auth/register", json={"email": "p@mu.ac.zm", "password": PASSWORD, "full_name": "Pat"})
    assert PASSWORD not in r.text and "hash" not in r.text
