"""R12: JIT provisioning, break-glass, gated impersonation, session
revocation, XML ingestion."""

import base64
import hashlib

from conftest import PASSWORD, auth, get_workspace, register_and_login

FAKE_CERT = b"idp-cert"
CERT_B64 = base64.b64encode(FAKE_CERT).decode()
DIGEST = hashlib.sha256(FAKE_CERT).hexdigest()


def saml(email):
    xml = (f'<r><ds:X509Certificate>{CERT_B64}</ds:X509Certificate>'
           f'<saml:NameID>{email}</saml:NameID></r>')
    return base64.b64encode(xml.encode()).decode()


async def test_jit_provisioning(client):
    tok = await register_and_login(client)
    await client.put("/api/v1/enterprise/sso", headers=auth(tok), json={
        "entity_id": "https://idp", "sso_url": "https://idp/sso",
        "cert_digest": DIGEST, "jit_provisioning": True,
        "jit_default_role": "analyst"})
    r = await client.post("/api/v1/enterprise/sso/acs/acme",
                          data={"SAMLResponse": saml("newbie@acme.dev")})
    assert r.status_code == 200 and r.json()["access_token"]
    scim = (await client.post("/api/v1/enterprise/scim/token",
                              headers=auth(tok))).json()["scim_token"]
    users = (await client.get("/api/v1/enterprise/scim/v2/Users",
                              headers={"Authorization": f"Bearer {scim}"})
             ).json()
    hit = next(u for u in users["Resources"]
               if u["userName"] == "newbie@acme.dev")
    assert hit["roles"] == ["analyst"]


async def test_break_glass_and_impersonation(client):
    tok = await register_and_login(client)
    r = await client.post("/api/v1/enterprise/break-glass", headers=auth(tok),
                          json={"reason": "IdP outage during quarter close"})
    assert r.status_code == 200 and r.json()["access_token"]
    assert (await client.post("/api/v1/enterprise/break-glass",
                              headers=auth(tok),
                              json={"reason": "short"})).status_code == 422
    scim = (await client.post("/api/v1/enterprise/scim/token",
                              headers=auth(tok))).json()["scim_token"]
    uid = (await client.post("/api/v1/enterprise/scim/v2/Users",
                             headers={"Authorization": f"Bearer {scim}"},
                             json={"userName": "member@acme.dev"})).json()["id"]
    # gated: no approval -> 403
    assert (await client.post(f"/api/v1/enterprise/impersonate/{uid}",
                              headers=auth(tok))).status_code == 403
    a = (await client.post("/api/v1/catalog/approvals", headers=auth(tok),
                           json={"kind": "impersonation", "subject_id": uid,
                                 "note": "debugging broken dashboard for "
                                         "ticket #4411"})).json()
    await client.post(f"/api/v1/catalog/approvals/{a['id']}/decide",
                      headers=auth(tok), json={"decision": "approve"})
    r = (await client.post(f"/api/v1/enterprise/impersonate/{uid}",
                           headers=auth(tok))).json()
    assert r["capped_role"] == "viewer"
    ws = await client.get("/api/v1/workspaces",
                          headers={"Authorization":
                                   f"Bearer {r['access_token']}"})
    assert ws.status_code == 200  # acting as the member, read-only role
    exp = (await client.get("/api/v1/enterprise/audit/export",
                            headers=auth(tok))).text
    assert "security.break_glass" in exp
    assert "security.impersonation" in exp


async def test_sessions_and_xml_upload(client):
    tok = await register_and_login(client)
    # second login -> second session
    await client.post("/api/v1/auth/login", json={
        "email": "owner@acme.dev", "password": PASSWORD,
        "tenant_slug": "acme"})
    sess = (await client.get("/api/v1/auth/sessions",
                             headers=auth(tok))).json()["sessions"]
    assert len(sess) >= 2
    r = await client.delete(f"/api/v1/auth/sessions/{sess[0]['id']}",
                            headers=auth(tok))
    assert r.status_code == 200
    left = (await client.get("/api/v1/auth/sessions",
                             headers=auth(tok))).json()["sessions"]
    assert len(left) == len(sess) - 1
    # XML ingestion through the trust pipeline
    ws = await get_workspace(client, tok)
    xml = ('<orders><order id="1"><region>South</region>'
           '<amount>100</amount></order>'
           '<order id="2"><region>North</region>'
           '<amount>50</amount></order></orders>')
    r = await client.post(
        f"/api/v1/datasets/upload-xml?workspace_id={ws}&name=xmlds"
        "&record_tag=order",
        headers=auth(tok), files={"file": ("o.xml", xml, "text/xml")})
    assert r.status_code == 201, r.text
    a = (await client.post(f"/api/v1/datasets/{r.json()['id']}/ask",
                           headers=auth(tok),
                           json={"question": "total amount"})).json()
    assert a["answer"]["value"] == 150
    assert (await client.post(
        f"/api/v1/datasets/upload-xml?workspace_id={ws}&name=bad"
        "&record_tag=order", headers=auth(tok),
        files={"file": ("b.xml", "<not-xml", "text/xml")})).status_code == 422
