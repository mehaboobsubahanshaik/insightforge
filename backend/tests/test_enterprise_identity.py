"""MVP5 G1: SAML SSO (pinned-cert ACS), SCIM provisioning, ABAC attributes,
access review workflows."""

import base64
import hashlib

from conftest import auth, register_and_login

FAKE_CERT_DER = b"fake-idp-certificate-der-bytes"
CERT_B64 = base64.b64encode(FAKE_CERT_DER).decode()
DIGEST = hashlib.sha256(FAKE_CERT_DER).hexdigest()


def saml_response(email: str, cert_b64: str = CERT_B64) -> str:
    xml = (f'<samlp:Response><ds:X509Certificate>{cert_b64}</ds:X509Certificate>'
           f'<saml:NameID Format="email">{email}</saml:NameID></samlp:Response>')
    return base64.b64encode(xml.encode()).decode()


async def test_saml_sso_pinned_cert_flow(client):
    tok = await register_and_login(client)  # acme, owner@acme.dev
    r = await client.put("/api/v1/enterprise/sso", headers=auth(tok), json={
        "entity_id": "https://idp.example.com", "sso_url": "https://idp.example.com/sso",
        "cert_digest": DIGEST})
    assert r.status_code == 200 and "acs_url" in r.json()
    meta = (await client.get("/api/v1/enterprise/sso/metadata/acme")).json()
    assert meta["entity_id"] == "insightforge:acme"
    # happy path: known member, matching cert
    r = await client.post("/api/v1/enterprise/sso/acs/acme",
                          data={"SAMLResponse": saml_response("owner@acme.dev")})
    assert r.status_code == 200 and r.json()["method"] == "saml"
    assert r.json()["access_token"]
    # wrong cert -> 401; unknown member -> 403
    bad = base64.b64encode(b"attacker-cert").decode()
    r = await client.post("/api/v1/enterprise/sso/acs/acme",
                          data={"SAMLResponse": saml_response("owner@acme.dev", bad)})
    assert r.status_code == 401
    r = await client.post("/api/v1/enterprise/sso/acs/acme",
                          data={"SAMLResponse": saml_response("ghost@acme.dev")})
    assert r.status_code == 403


async def test_scim_provision_list_deprovision(client):
    tok = await register_and_login(client)
    scim = (await client.post("/api/v1/enterprise/scim/token",
                              headers=auth(tok))).json()["scim_token"]
    h = {"Authorization": f"Bearer {scim}"}
    r = await client.post("/api/v1/enterprise/scim/v2/Users", headers=h,
                          json={"userName": "new.hire@acme.dev",
                                "displayName": "New Hire"})
    assert r.status_code == 201
    uid = r.json()["id"]
    listing = (await client.get("/api/v1/enterprise/scim/v2/Users",
                                headers=h)).json()
    assert listing["totalResults"] == 2  # owner + provisioned
    r = await client.delete(f"/api/v1/enterprise/scim/v2/Users/{uid}", headers=h)
    assert r.status_code == 204
    assert (await client.get("/api/v1/enterprise/scim/v2/Users",
                             headers=h)).json()["totalResults"] == 1
    # bad token 401
    assert (await client.get("/api/v1/enterprise/scim/v2/Users",
                             headers={"Authorization": "Bearer nope"})
            ).status_code == 401


async def test_abac_attributes_and_access_review(client):
    tok = await register_and_login(client)
    scim = (await client.post("/api/v1/enterprise/scim/token",
                              headers=auth(tok))).json()["scim_token"]
    uid = (await client.post("/api/v1/enterprise/scim/v2/Users",
                             headers={"Authorization": f"Bearer {scim}"},
                             json={"userName": "temp@acme.dev"})).json()["id"]
    r = await client.put("/api/v1/enterprise/members/attributes",
                         headers=auth(tok),
                         json={"user_id": uid,
                               "attributes": {"department": "finance"}})
    assert r.json()["attributes"] == {"department": "finance"}
    # review: snapshot -> revoke the temp -> membership gone, review closes
    rev = (await client.post("/api/v1/enterprise/access-reviews",
                             headers=auth(tok))).json()
    assert len(rev["items"]) == 2
    owner = next(i for i in rev["items"] if i["email"] == "owner@acme.dev")
    temp = next(i for i in rev["items"] if i["email"] == "temp@acme.dev")
    assert temp["attributes"] == {"department": "finance"}
    await client.post(f"/api/v1/enterprise/access-reviews/{rev['id']}/decide",
                      headers=auth(tok),
                      json={"user_id": owner["user_id"], "decision": "approve"})
    r = await client.post(f"/api/v1/enterprise/access-reviews/{rev['id']}/decide",
                          headers=auth(tok),
                          json={"user_id": temp["user_id"], "decision": "revoke"})
    assert r.json()["status"] == "closed"
    listing = (await client.get("/api/v1/enterprise/scim/v2/Users",
                                headers={"Authorization": f"Bearer {scim}"})).json()
    assert listing["totalResults"] == 1  # revoked member removed
