"""Public API v1 (MVP3 P5): scoped API keys for programmatic access.

Key format: ``ifk_<prefix>_<secret>`` — shown once at creation; only a
SHA-256 hash is stored. Auth via ``X-API-Key`` header. Every request runs
inside the key's tenant RLS scope with its scopes enforced, and is audited.
Docs: docs/API.md.
"""

import hashlib
import secrets as pysecrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit
from ..db import tenant_scoped_session
from ..deps import TenantContext, get_session, require
from ..models import APIKey, Dataset, uuid7
from ..services import querysvc

router = APIRouter(prefix="/api/v1", tags=["public-api"])
SCOPES = ("data:read",)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


# ---- key management (session auth) ----
class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default=["data:read"])


@router.post("/api-keys", status_code=201)
async def create_key(body: KeyIn,
                     ctx: TenantContext = Depends(require("tenant:manage")),
                     session=Depends(get_session)):
    if any(s not in SCOPES for s in body.scopes):
        raise HTTPException(422, f"Unknown scope; available: {list(SCOPES)}")
    prefix = pysecrets.token_hex(4)
    secret = pysecrets.token_hex(20)
    key = APIKey(id=uuid7(), tenant_id=ctx.tenant_id, name=body.name,
                 prefix=prefix, key_hash=_hash(secret), scopes=body.scopes)
    session.add(key)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="apikey.create",
                       resource_type="api_key", resource_id=str(key.id))
    await session.commit()
    return {"id": str(key.id), "name": key.name, "scopes": key.scopes,
            "api_key": f"ifk_{prefix}_{secret}",
            "note": "Store this now — it is shown only once."}


@router.get("/api-keys")
async def list_keys(ctx: TenantContext = Depends(require("tenant:manage")),
                    session=Depends(get_session)):
    keys = (await session.execute(select(APIKey).where(
        APIKey.tenant_id == ctx.tenant_id))).scalars().all()
    return {"keys": [{"id": str(k.id), "name": k.name, "prefix": k.prefix,
                      "scopes": k.scopes, "active": k.active,
                      "last_used_at": k.last_used_at.isoformat()
                      if k.last_used_at else None} for k in keys]}


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_key(key_id: str,
                     ctx: TenantContext = Depends(require("tenant:manage")),
                     session=Depends(get_session)):
    k = (await session.execute(select(APIKey).where(
        APIKey.id == key_id,
        APIKey.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if k is None:
        raise HTTPException(404, "Key not found")
    k.active = False
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="apikey.revoke",
                       resource_type="api_key", resource_id=key_id)
    await session.commit()
    return None


# ---- key-authenticated data endpoints ----
async def _key_auth(x_api_key: str = Header(default=""),
                    scope: str = "data:read") -> APIKey:
    parts = (x_api_key or "").split("_")
    if len(parts) != 3 or parts[0] != "ifk":
        raise HTTPException(401, "Missing or malformed X-API-Key")
    _, prefix, secret = parts
    from ..db import session_factory

    async with session_factory()() as s:
        k = (await s.execute(select(APIKey).where(
            APIKey.prefix == prefix))).scalar_one_or_none()
        if k is None or not k.active or k.key_hash != _hash(secret):
            raise HTTPException(401, "Invalid or revoked API key")
        if scope not in (k.scopes or []):
            raise HTTPException(403, f"Key lacks scope '{scope}'")
        k.last_used_at = datetime.now(timezone.utc)
        await s.commit()
        return k


@router.get("/public/datasets")
async def public_datasets(key: APIKey = Depends(_key_auth)):
    async with tenant_scoped_session(key.tenant_id) as s:
        rows = (await s.execute(select(Dataset).where(
            Dataset.tenant_id == key.tenant_id,
            Dataset.archived.is_(False)))).scalars().all()
        return {"datasets": [{"id": str(d.id), "name": d.name,
                              "rows": d.row_count,
                              "quality_score": d.quality_score,
                              "columns": [c["name"] for c in d.schema_def]}
                             for d in rows]}


class QueryIn(BaseModel):
    formula: str = Field(min_length=1, max_length=500)
    group_by: str | None = None


@router.post("/public/datasets/{dataset_id}/query")
async def public_query(dataset_id: str, body: QueryIn,
                       key: APIKey = Depends(_key_auth)):
    """Governed query: the same formulas-only path the UI uses — an API key
    can never reach raw SQL either."""
    async with tenant_scoped_session(key.tenant_id) as s:
        d = (await s.execute(select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.tenant_id == key.tenant_id))).scalar_one_or_none()
        if d is None:
            raise HTTPException(404, "Dataset not found")
        try:
            result = await querysvc.execute_formula(
                s, dataset_id=d.id, current_import_id=d.current_import_id,
                dataset_schema=d.schema_def, formula=body.formula,
                group_by=body.group_by, filters=[])
        except querysvc.QueryError as e:
            raise HTTPException(422, str(e)) from None
        await audit.record(s, tenant_id=key.tenant_id, actor_user_id=None,
                           action="api.query", resource_type="dataset",
                           resource_id=str(d.id))
        await s.commit()
        return {"dataset": d.name, "formula": body.formula, **result,
                "quality_score": d.quality_score}
