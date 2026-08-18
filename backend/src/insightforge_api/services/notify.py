"""Notification delivery (MVP3 chapter 4): HMAC-signed webhooks with
Slack/Teams formatting.

Delivery contract:
- Payloads are signed: X-InsightForge-Signature = HMAC-SHA256(secret, body),
  so receivers can verify authenticity — the standard defense against forged
  webhook calls.
- Formats: 'generic' posts the full event JSON; 'slack' and 'teams' post the
  {"text": message} shape their incoming webhooks expect.
- Dev/test parity with the mailer: when WEBHOOK_MODE=outbox (the compose and
  test default), deliveries are written as .webhook.json files to the mail
  outbox dir instead of leaving the machine — provable locally, no network.
- Failures never break the calling flow (an unreachable Slack must not fail
  a report run); they are recorded on the webhook's last_status instead.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import Webhook
from .mailer import outbox_dir

log = logging.getLogger("insightforge.notify")

EVENTS = ("alert.triggered", "anomaly.detected", "sync.failed",
          "report.sent", "siem.audit", "forecast.breach")


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _format(fmt: str, event: str, payload: dict) -> dict:
    if fmt in ("slack", "teams"):
        return {"text": f"[InsightForge] {payload.get('message', event)}"}
    return {"event": event, "payload": payload,
            "sent_at": datetime.now(timezone.utc).isoformat()}


async def deliver_event(session, tenant_id, event: str, payload: dict) -> int:
    """Deliver an event to every active subscribed webhook. Returns count."""
    hooks = (await session.execute(select(Webhook).where(
        Webhook.tenant_id == tenant_id, Webhook.active.is_(True)))
    ).scalars().all()
    delivered = 0
    for hook in hooks:
        if event not in (hook.events or []):
            continue
        body = json.dumps(_format(hook.format, event, payload),
                          separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json",
                   "X-InsightForge-Event": event,
                   "X-InsightForge-Signature": sign(hook.secret, body)}
        try:
            if os.environ.get("WEBHOOK_MODE", "outbox") == "outbox":
                d = outbox_dir()
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{uuid.uuid4().hex}.webhook.json").write_text(
                    json.dumps({"url": hook.url, "headers": headers,
                                "body": body.decode()}, indent=1))
                hook.last_status = "delivered (outbox)"
            else:  # pragma: no cover - real network path
                import httpx

                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.post(hook.url, content=body,
                                             headers=headers)
                hook.last_status = f"HTTP {resp.status_code}"
            hook.last_delivery_at = datetime.now(timezone.utc)
            delivered += 1
        except Exception as e:  # noqa: BLE001 - delivery must never break callers
            hook.last_status = f"failed: {e}"[:255]
            log.warning("webhook %s delivery failed: %s", hook.id, e)
    return delivered
