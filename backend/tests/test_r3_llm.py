"""R3: LLM abstraction — deterministic fallback, redaction before egress,
mocked external provider, cost + audit metering."""

from datetime import date, timedelta

import asyncpg
from conftest import ADMIN_DSN, auth, get_workspace, register_and_login, upload_csv

from insightforge_api.services.llm import LLMClient, redact


def test_redaction_strips_pii_tokens():
    s = "Contact a@x.io or +91 98765 43210 about revenue 1200"
    r = redact(s)
    assert "a@x.io" not in r and "[REDACTED]" in r
    assert "revenue 1200" in r  # numbers/business text untouched


def _csv():
    t = date.today()
    return ("order_date,region,revenue\n"
            f"{(t - timedelta(days=35)).isoformat()},South,1000\n"
            f"{(t - timedelta(days=5)).isoformat()},South,1600\n")


async def test_deterministic_fallback_and_metering(client):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="fin", content=_csv())
    st = (await client.get("/api/v1/ai/provider", headers=auth(tok))).json()
    assert st["provider"] == "deterministic"
    assert "PII redaction before egress" in st["guardrails"]
    r = (await client.post("/api/v1/ai/summarize", headers=auth(tok),
                           json={"dataset_id": ds["id"]})).json()
    assert r["provider"] == "deterministic"
    assert "fin" in r["grounded_text"] and r["text"] == r["grounded_text"]
    conn = await asyncpg.connect(ADMIN_DSN)
    n = await conn.fetchval(
        "SELECT count(*) FROM billing_events WHERE kind='ai.tokens'")
    await conn.close()
    assert n == 1  # every call metered, even deterministic


async def test_external_provider_mocked_redacts_and_grounds(client,
                                                            monkeypatch):
    tok = await register_and_login(client)
    ws = await get_workspace(client, tok)
    ds = await upload_csv(client, tok, ws, name="fin", content=_csv())
    sent = {}

    async def fake_post(self, payload):
        sent["payload"] = payload
        return {"choices": [{"message": {"content": "Rephrased summary."}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7}}

    monkeypatch.setattr(LLMClient, "_post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    import insightforge_api.services.llm as llmmod
    monkeypatch.setattr(llmmod, "client", LLMClient())
    monkeypatch.setattr(llmmod.client, "api_url", "https://llm.example/v1")
    monkeypatch.setattr(llmmod.client, "api_key", "k")
    r = (await client.post("/api/v1/ai/summarize", headers=auth(tok),
                           json={"dataset_id": ds["id"],
                                 "question": "email me at boss@acme.dev "
                                             "with the summary"})).json()
    assert r["provider"] == "openai-compatible"
    assert r["text"] == "Rephrased summary."
    assert r["tokens_in"] == 42 and "grounded_text" in r
    user_msg = sent["payload"]["messages"][1]["content"]
    assert "boss@acme.dev" not in user_msg          # redacted before egress
    assert "[REDACTED]" in user_msg
    assert "Do not invent numbers" in sent["payload"]["messages"][0]["content"]
