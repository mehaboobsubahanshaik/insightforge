"""Webhook management (MVP3 P2): tenant-scoped notification endpoints.

Secrets are generated server-side and shown ONCE at creation (receivers
verify X-InsightForge-Signature with it); the list endpoint never returns
them. Slack/Teams incoming-webhook URLs are first-class formats.
"""

import secrets as pysecrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import Webhook, uuid7
from ..services import notify

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class WebhookIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=2000, pattern="^https?://")
    format: str = Field(default="generic", pattern="^(generic|slack|teams)$")
    events: list[str] = Field(default_factory=list)


class WebhookPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=8, max_length=2000,
                            pattern="^https?://")
    format: str | None = Field(default=None,
                               pattern="^(generic|slack|teams)$")
    events: list[str] | None = None
    active: bool | None = None


def _validate_events(events: list[str]) -> list[str]:
    bad = [e for e in events if e not in notify.EVENTS]
    if bad:
        raise HTTPException(422, f"Unknown events {bad}. "
                                 f"Available: {list(notify.EVENTS)}")
    return events


def _public(h: Webhook) -> dict:
    return {"id": str(h.id), "name": h.name, "url": h.url,
            "format": h.format, "events": h.events, "active": h.active,
            "last_status": h.last_status,
            "last_delivery_at": h.last_delivery_at.isoformat()
            if h.last_delivery_at else None}


@router.get("")
async def list_webhooks(ctx: TenantContext = Depends(require("tenant:manage")),
                        session=Depends(get_session)):
    hooks = (await session.execute(select(Webhook).where(
        Webhook.tenant_id == ctx.tenant_id).order_by(
        Webhook.created_at))).scalars().all()
    return {"webhooks": [_public(h) for h in hooks],
            "available_events": list(notify.EVENTS)}


@router.post("", status_code=201)
async def create_webhook(body: WebhookIn,
                         ctx: TenantContext = Depends(require("tenant:manage")),
                         session=Depends(get_session)):
    secret = pysecrets.token_hex(24)
    hook = Webhook(id=uuid7(), tenant_id=ctx.tenant_id, name=body.name,
                   url=body.url, secret=secret, format=body.format,
                   events=_validate_events(body.events))
    session.add(hook)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="webhook.create",
                       resource_type="webhook", resource_id=str(hook.id))
    await session.commit()
    return {**_public(hook), "secret": secret,
            "note": "Store the secret now — it is shown only once. Verify "
                    "deliveries via X-InsightForge-Signature = "
                    "HMAC-SHA256(secret, body)."}


@router.patch("/{webhook_id}")
async def update_webhook(webhook_id: str, body: WebhookPatch,
                         ctx: TenantContext = Depends(require("tenant:manage")),
                         session=Depends(get_session)):
    hook = (await session.execute(select(Webhook).where(
        Webhook.id == webhook_id,
        Webhook.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if hook is None:
        raise HTTPException(404, "Webhook not found")
    for field in ("name", "url", "format", "active"):
        v = getattr(body, field)
        if v is not None:
            setattr(hook, field, v)
    if body.events is not None:
        hook.events = _validate_events(body.events)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="webhook.update",
                       resource_type="webhook", resource_id=str(hook.id))
    await session.commit()
    return _public(hook)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str,
                         ctx: TenantContext = Depends(require("tenant:manage")),
                         session=Depends(get_session)):
    hook = (await session.execute(select(Webhook).where(
        Webhook.id == webhook_id,
        Webhook.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if hook is None:
        raise HTTPException(404, "Webhook not found")
    await session.delete(hook)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="webhook.delete",
                       resource_type="webhook", resource_id=webhook_id)
    await session.commit()
    return None


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str,
                       ctx: TenantContext = Depends(require("tenant:manage")),
                       session=Depends(get_session)):
    hook = (await session.execute(select(Webhook).where(
        Webhook.id == webhook_id,
        Webhook.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if hook is None:
        raise HTTPException(404, "Webhook not found")
    saved_events = hook.events
    hook.events = list(notify.EVENTS)  # a test delivers regardless of filter
    delivered = await notify.deliver_event(
        session, ctx.tenant_id, "alert.triggered",
        {"message": f"Test delivery for webhook '{hook.name}' — "
                    "your endpoint and signature verification are working."})
    hook.events = saved_events
    await session.commit()
    return {"delivered": delivered, "last_status": hook.last_status}
