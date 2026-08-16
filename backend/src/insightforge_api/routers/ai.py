"""AI feedback endpoints (MVP3 chapter 3): capture thumbs on any AI output.

Kept as its own router because feedback spans surfaces (dataset questions,
dashboard briefs, prep suggestions). Feedback is tenant-scoped (RLS) and the
list is readable by admins/owners — the evidence base for judging whether
the AI layer helps, which is what "AI feedback capture" exists to answer.
"""

from fastapi import APIRouter, Depends
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
