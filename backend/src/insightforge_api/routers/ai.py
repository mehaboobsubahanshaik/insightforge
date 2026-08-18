"""AI feedback endpoints (MVP3 chapter 3): capture thumbs on any AI output.

Kept as its own router because feedback spans surfaces (dataset questions,
dashboard briefs, prep suggestions). Feedback is tenant-scoped (RLS) and the
list is readable by admins/owners — the evidence base for judging whether
the AI layer helps, which is what "AI feedback capture" exists to answer.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import AIFeedback, uuid7

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

KINDS = {"question", "brief", "prep_suggestion", "explanation"}


class FeedbackIn(BaseModel):
    kind: str = Field(pattern="^(question|brief|prep_suggestion|explanation)$")
    subject: str = Field(min_length=1, max_length=500)
    helpful: bool
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/feedback", status_code=201)
async def leave_feedback(body: FeedbackIn,
                         ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    fb = AIFeedback(id=uuid7(), tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id, kind=body.kind,
                    subject=body.subject[:500], helpful=body.helpful,
                    comment=body.comment)
    session.add(fb)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="ai.feedback",
                       resource_type="ai_feedback", resource_id=str(fb.id))
    await session.commit()
    return {"id": str(fb.id), "recorded": True,
            "note": "Thanks — feedback is reviewed against the AI evaluation "
                    "suite (docs/AI-EVALS.md)."}


@router.get("/feedback")
async def list_feedback(ctx: TenantContext = Depends(require("tenant:manage")),
                        session=Depends(get_session)):
    rows = (await session.execute(select(AIFeedback).where(
        AIFeedback.tenant_id == ctx.tenant_id).order_by(
        desc(AIFeedback.created_at)).limit(200))).scalars().all()
    helpful = sum(1 for r in rows if r.helpful)
    return {"total": len(rows), "helpful": helpful,
            "unhelpful": len(rows) - helpful,
            "items": [{"id": str(r.id), "kind": r.kind, "subject": r.subject,
                       "helpful": r.helpful, "comment": r.comment,
                       "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/provider")
async def llm_provider_status(ctx: TenantContext = Depends(
        require("dataset:read"))):
    """R3: which brain answers. Deterministic engine is always present;
    an external provider only rephrases grounded text (never invents)."""
    from ..services.llm import client

    return {"provider": client.provider if client.external
            else "deterministic",
            "external_configured": client.external,
            "guardrails": ["ai quota", "PII redaction before egress",
                           "grounded-text-only prompting",
                           "token + latency metering", "full audit"]}


class SummarizeIn(BaseModel):
    dataset_id: str
    question: str = Field(default="summarize recent performance",
                          max_length=500)


@router.post("/summarize")
async def summarize(body: SummarizeIn,
                    ctx: TenantContext = Depends(require("dataset:read")),
                    session=Depends(get_session)):
    """R3: grounded summary — deterministic engine computes; the configured
    provider (if any) only rephrases. Provenance always attached."""
    from sqlalchemy import select as _sel

    from ..models import Dataset
    from ..services import narrative
    from ..services.llm import client

    ds = (await session.execute(_sel(Dataset).where(
        Dataset.id == body.dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    num = next((c["name"] for c in ds.schema_def
                if c["inferred_type"] in ("number", "integer")), None)
    dat = next((c["name"] for c in ds.schema_def
                if c["inferred_type"] in ("date", "timestamp")), None)
    if not num or not dat:
        raise HTTPException(422, "Need a numeric and a date column")
    drv = next((c["name"] for c in ds.schema_def
                if c["inferred_type"] == "text"), None)
    pop = await narrative.pop_kpi(session, ds, f"sum({num})", dat, drv)
    grounded = (f"{ds.name}: {num} is {narrative._fmt(pop['current'])} "
                f"({pop['pct']} vs the prior window)."
                + narrative.driver_sentence(pop["change"], pop["drivers"],
                                            drv or ""))
    out = await client.complete(session, ctx.tenant_id, ctx.user_id,
                                prompt=f"{body.question}\n\n{grounded}",
                                grounded_text=grounded)
    await session.commit()
    return out
