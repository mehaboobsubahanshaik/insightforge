"""LLM provider abstraction (R3, per ADR-003): every provider call passes
the SAME guardrails — AI quota, PII redaction before egress, audit, token
cost metering. Without a configured provider the platform stays fully
functional on the deterministic engine (the fallback AND the grounding).

Env config (platform-level):
  LLM_PROVIDER = deterministic (default) | openai-compatible
  LLM_API_URL  = e.g. https://api.openai.com/v1/chat/completions
                 or an Azure OpenAI deployment URL
  LLM_API_KEY, LLM_MODEL
"""

import os
import re
import time

import httpx

from .. import audit
from . import entitlements
from .pii import PATTERNS

REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Strip PII token-by-token before any external egress."""
    out = []
    for tok in re.split(r"(\s+)", text or ""):
        bare = tok.strip().strip(",.;:()[]")
        out.append(tok if not bare or not any(
            rx.match(bare) for rx in PATTERNS.values()) else REDACTED)
    return "".join(out)


class LLMClient:
    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "deterministic")
        self.api_url = os.environ.get("LLM_API_URL", "")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    @property
    def external(self) -> bool:
        return (self.provider == "openai-compatible"
                and bool(self.api_url) and bool(self.api_key))

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self.api_url, json=payload, headers={
                "Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            return r.json()

    async def complete(self, session, tenant_id, actor_user_id, *,
                       prompt: str, grounded_text: str) -> dict:
        """Guardrailed completion. grounded_text is the deterministic
        engine's answer — always returned, never overridden by the model;
        the LLM only rephrases what the governed layer computed."""
        await entitlements.enforce_ai_quota(session, tenant_id)
        start = time.monotonic()
        if not self.external:
            result = {"text": grounded_text, "provider": "deterministic",
                      "model": None, "tokens_in": 0, "tokens_out": 0}
        else:
            safe_prompt = redact(prompt)
            data = await self._post({
                "model": self.model,
                "messages": [
                    {"role": "system",
                     "content": "Rephrase the provided grounded analytics "
                                "text for a business reader. Do not invent "
                                "numbers; every figure must come from the "
                                "grounded text."},
                    {"role": "user", "content": safe_prompt}]})
            usage = data.get("usage", {})
            result = {"text": data["choices"][0]["message"]["content"],
                      "provider": "openai-compatible", "model": self.model,
                      "tokens_in": usage.get("prompt_tokens", 0),
                      "tokens_out": usage.get("completion_tokens", 0)}
        result["latency_ms"] = int((time.monotonic() - start) * 1000)
        result["grounded_text"] = grounded_text
        await entitlements.record_billing_event(
            session, tenant_id, "ai.tokens")
        await audit.record(session, tenant_id=tenant_id,
                           actor_user_id=actor_user_id, action="ai.llm",
                           resource_type="llm", resource_id=self.provider,
                           detail={"tokens_in": result["tokens_in"],
                                   "tokens_out": result["tokens_out"],
                                   "latency_ms": result["latency_ms"]})
        return result


client = LLMClient()
