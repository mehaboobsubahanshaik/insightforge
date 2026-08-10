"""MFA recovery codes: minted at enable, one-time login use, regeneration."""

import pytest

from insightforge_api.security import totp_now

from conftest import PASSWORD, register_and_login

pytestmark = pytest.mark.anyio


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _new_user(client, slug):
    email = f"owner@{slug}.dev"
    bundle = await register_and_login(client, slug=slug, email=email,
                                      name=f"{slug.title()} Inc")
    return bundle["access_token"], email


async def _enable_mfa(client, tok):
    secret = (await client.post("/api/v1/auth/mfa/setup",
                                headers=auth(tok))).json()["secret"]
    r = await client.post("/api/v1/auth/mfa/enable", headers=auth(tok),
                          json={"otp": totp_now(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()


async def test_enable_returns_ten_single_use_codes(client):
    tok, email = await _new_user(client, "recov1")
    _, enabled = await _enable_mfa(client, tok)
    codes = enabled["recovery_codes"]
    assert len(codes) == 10
    assert all(len(c) == 9 and c[4] == "-" for c in codes)

    # TOTP-less login with a recovery code succeeds…
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": PASSWORD,
                                "otp": codes[0]})
    assert r.status_code == 200, r.text

    # …and that code is consumed: second use fails
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": PASSWORD,
                                "otp": codes[0]})
    assert r.status_code == 401

    # a different unused code still works (normalization: lowercase, no dash)
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": PASSWORD,
                                "otp": codes[1].replace("-", "").lower()})
    assert r.status_code == 200, r.text


async def test_totp_still_works_and_garbage_rejected(client):
    tok, email = await _new_user(client, "recov2")
    secret, _ = await _enable_mfa(client, tok)
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": PASSWORD,
                                "otp": totp_now(secret)})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": PASSWORD,
                                "otp": "ZZZZ-ZZZZ"})
    assert r.status_code == 401


async def test_regenerate_invalidates_old_set(client):
    tok, email = await _new_user(client, "recov3")
    _, enabled = await _enable_mfa(client, tok)
    old = enabled["recovery_codes"]

    # wrong password refused
    r = await client.post("/api/v1/auth/mfa/recovery-codes", headers=auth(tok),
                          json={"password": "not-the-password"})
    assert r.status_code == 401

    r = await client.post("/api/v1/auth/mfa/recovery-codes", headers=auth(tok),
                          json={"password": PASSWORD})
    assert r.status_code == 200
    fresh = r.json()["recovery_codes"]
    assert len(fresh) == 10 and set(fresh).isdisjoint(old)

    # an old code no longer logs in; a fresh one does
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": PASSWORD,
                                "otp": old[3]})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/login",
                          json={"email": email, "password": PASSWORD,
                                "otp": fresh[0]})
    assert r.status_code == 200, r.text