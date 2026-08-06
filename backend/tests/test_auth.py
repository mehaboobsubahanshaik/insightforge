"""Authentication & identity lifecycle."""

from conftest import (
    PASSWORD,
    auth,
    register_and_login,
    token_from_outbox,
)


async def test_register_creates_tenant_owner_and_workspace(client):
    tok = await register_and_login(client)
    assert tok["role"] == "tenant_owner" and tok["tenant_slug"] == "acme"
    r = await client.get("/api/v1/workspaces", headers=auth(tok))
    assert [w["name"] for w in r.json()] == ["Main workspace"]


async def test_duplicate_slug_and_email_conflict(client):
    await register_and_login(client)
    r = await client.post("/api/v1/auth/register", json={
        "tenant_name": "Other", "tenant_slug": "acme", "email": "x@y.dev",
        "password": PASSWORD, "display_name": "X"})
    assert r.status_code == 409 and "slug" in r.json()["detail"]
    r = await client.post("/api/v1/auth/register", json={
        "tenant_name": "Other", "tenant_slug": "other", "email": "owner@acme.dev",
        "password": PASSWORD, "display_name": "X"})
    assert r.status_code == 409


async def test_login_wrong_password_and_tenant_slug(client):
    await register_and_login(client)
    r = await client.post("/api/v1/auth/login", json={
        "email": "owner@acme.dev", "password": "wrong-password-123"})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={
        "email": "owner@acme.dev", "password": PASSWORD, "tenant_slug": "acme"})
    assert r.status_code == 200 and r.json()["tenant_slug"] == "acme"
    r = await client.post("/api/v1/auth/login", json={
        "email": "owner@acme.dev", "password": PASSWORD, "tenant_slug": "nope"})
    assert r.status_code == 401


async def test_refresh_rotation_and_replay(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    assert new["access_token"] and new["refresh_token"] != tok["refresh_token"]
    # replaying the consumed token must fail (rotation)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert r.status_code == 200


async def test_logout_revokes_refresh(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/auth/logout", headers=auth(tok),
                          json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 204
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401


async def test_email_verification_flow(client):
    tok = await register_and_login(client)
    assert tok["email_verified"] is False
    raw = token_from_outbox(r"token:\n\n(\S+)")
    r = await client.post("/api/v1/auth/verify-email", headers=auth(tok),
                          json={"token": "wrong"})
    assert r.status_code == 400
    r = await client.post("/api/v1/auth/verify-email", headers=auth(tok),
                          json={"token": raw})
    assert r.status_code == 200 and r.json()["email_verified"] is True
    me = (await client.get("/api/v1/auth/me", headers=auth(tok))).json()
    assert me["email_verified"] is True


async def test_password_reset_flow(client):
    tok = await register_and_login(client)
    # unknown address: still 202, no enumeration
    r = await client.post("/api/v1/auth/password-reset/request",
                          json={"email": "ghost@nowhere.dev"})
    assert r.status_code == 202
    r = await client.post("/api/v1/auth/password-reset/request",
                          json={"email": "owner@acme.dev"})
    assert r.status_code == 202
    raw = token_from_outbox(r"Token:\n(\S+)")
    r = await client.post("/api/v1/auth/password-reset/confirm",
                          json={"token": raw, "new_password": "brand-new-password-1"})
    assert r.status_code == 200
    # old password dead, new one works, old refresh revoked
    r = await client.post("/api/v1/auth/login",
                          json={"email": "owner@acme.dev", "password": PASSWORD})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/login",
                          json={"email": "owner@acme.dev",
                                "password": "brand-new-password-1"})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401


async def test_change_password(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/auth/password/change", headers=auth(tok),
                          json={"current_password": "nope-nope-nope",
                                "new_password": "another-new-pass-1"})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/password/change", headers=auth(tok),
                          json={"current_password": PASSWORD,
                                "new_password": "another-new-pass-1"})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/login", json={
        "email": "owner@acme.dev", "password": "another-new-pass-1"})
    assert r.status_code == 200


async def test_profile_get_and_patch(client):
    tok = await register_and_login(client)
    me = (await client.get("/api/v1/auth/me", headers=auth(tok))).json()
    assert me["email"] == "owner@acme.dev" and me["role"] == "tenant_owner"
    r = await client.patch("/api/v1/auth/me", headers=auth(tok),
                           json={"display_name": "Captain Owner"})
    assert r.json()["display_name"] == "Captain Owner"


async def test_mfa_setup_enable_and_step_up(client):
    import pyotp

    tok = await register_and_login(client)
    secret = (await client.post("/api/v1/auth/mfa/setup",
                                headers=auth(tok))).json()["secret"]
    r = await client.post("/api/v1/auth/mfa/enable", headers=auth(tok),
                          json={"otp": "000000"})
    assert r.status_code == 400
    code = pyotp.TOTP(secret).now()
    r = await client.post("/api/v1/auth/mfa/enable", headers=auth(tok), json={"otp": code})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/login",
                          json={"email": "owner@acme.dev", "password": PASSWORD})
    assert r.status_code == 428  # MFA step-up demanded
    r = await client.post("/api/v1/auth/login", json={
        "email": "owner@acme.dev", "password": PASSWORD,
        "otp": pyotp.TOTP(secret).now()})
    assert r.status_code == 200


async def test_invitation_accept_and_replay(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/members/invitations", headers=auth(tok),
                          json={"email": "newbie@acme.dev", "role": "analyst"})
    assert r.status_code == 201
    raw = token_from_outbox(r"token:\n(\S+)")
    r = await client.post("/api/v1/auth/invitations/accept", json={
        "token": raw, "password": "newbie-password-1", "display_name": "Newbie"})
    assert r.status_code == 200 and r.json()["role"] == "analyst"
    # one-time use
    r = await client.post("/api/v1/auth/invitations/accept", json={
        "token": raw, "password": "newbie-password-1"})
    assert r.status_code == 400
    members = (await client.get("/api/v1/members", headers=auth(tok))).json()
    assert {m["email"] for m in members} == {"owner@acme.dev", "newbie@acme.dev"}


async def test_invalid_role_rejected(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/members/invitations", headers=auth(tok),
                          json={"email": "x@acme.dev", "role": "superuser"})
    assert r.status_code == 422


async def test_expired_access_token_rejected(client, monkeypatch):
    import insightforge_api.security as sec

    tok = await register_and_login(client)
    real_time = sec.time.time
    monkeypatch.setattr(sec.time, "time", lambda: real_time() + 3600 * 24)
    r = await client.get("/api/v1/auth/me", headers=auth(tok))
    assert r.status_code == 401


async def test_missing_and_garbage_bearer(client):
    r = await client.get("/api/v1/datasets")
    assert r.status_code == 401
    r = await client.get("/api/v1/datasets", headers={"Authorization": "Bearer junk.junk.junk"})
    assert r.status_code == 401
