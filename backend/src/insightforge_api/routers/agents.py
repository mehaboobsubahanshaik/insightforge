"""Agent APIs (MVP6 A1): list + run domain agents. Observation-only by
design — recommendations flow into the A2 approval workflow before any
action. Every run audited + AI-quota-metered."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import audit
from ..deps import TenantContext, get_session, require
from ..models import Dashboard, Dataset, uuid7
from ..services import agents as agentsvc
from ..services import entitlements

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("")
async def list_agents(ctx: TenantContext = Depends(require("dataset:read"))):
    return {"agents": [
        {"name": n, "mode": "observe+recommend",
         "action_policy": "recommendations require human approval (A2); "
                          "agents never change data or settings"}
        for n in agentsvc.AGENTS]}


@router.post("/{name}/run")
async def run(name: str,
              ctx: TenantContext = Depends(require("dataset:read")),
              session=Depends(get_session)):
    if name not in agentsvc.AGENTS:
        raise HTTPException(404, f"Unknown agent; available: "
                                 f"{list(agentsvc.AGENTS)}")
    await entitlements.enforce_ai_quota(session, ctx.tenant_id)
    datasets = (await session.execute(select(Dataset).where(
        Dataset.tenant_id == ctx.tenant_id,
        Dataset.archived.is_(False)))).scalars().all()
    dashboards = (await session.execute(select(Dashboard).where(
        Dashboard.tenant_id == ctx.tenant_id))).scalars().all()
    ds_by_id = {str(d.id): d for d in datasets}
    report = await agentsvc.run_agent(session, ctx.tenant_id, name,
                                      datasets, dashboards, ds_by_id)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="ai.agent",
                       resource_type="agent", resource_id=name)
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="ai.question",
                       resource_type="agent", resource_id=name)
    await session.commit()
    return report


CONF_W = {"high": 1.0, "medium": 0.6, "low": 0.3}


@router.post("/orchestrate")
async def orchestrate(ctx: TenantContext = Depends(require("dataset:read")),
                      session=Depends(get_session)):
    """Multi-agent orchestration: run every agent, merge, and RANK
    recommendations by expected_impact x confidence."""
    await entitlements.enforce_ai_quota(session, ctx.tenant_id)
    datasets = (await session.execute(select(Dataset).where(
        Dataset.tenant_id == ctx.tenant_id,
        Dataset.archived.is_(False)))).scalars().all()
    dashboards = (await session.execute(select(Dashboard).where(
        Dashboard.tenant_id == ctx.tenant_id))).scalars().all()
    ds_by_id = {str(d.id): d for d in datasets}
    reports, merged = {}, []
    for name in agentsvc.AGENTS:
        rep = await agentsvc.run_agent(session, ctx.tenant_id, name,
                                       datasets, dashboards, ds_by_id)
        reports[name] = rep
        for rec in rep.get("recommendations", []):
            impact = rec.get("expected_impact")
            score = (float(impact) if isinstance(impact, (int, float))
                     else 1.0) * CONF_W.get(rec.get("confidence"), .5)
            merged.append({**rec, "agent": name, "score": round(score, 2)})
    merged.sort(key=lambda r: -r["score"])
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="ai.orchestrate",
                       resource_type="agent", resource_id="all")
    await session.commit()
    return {"agents_run": list(reports),
            "grounded": {n: r.get("grounded") for n, r in reports.items()},
            "ranked_recommendations": merged[:10],
            "note": "Turn top recommendations into an action plan "
                    "(POST /agents/plans) — execution requires approval."}


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    steps: list[str] = Field(min_length=1, max_length=10)
    metric_dataset_id: str
    metric_formula: str = Field(min_length=1, max_length=500)


@router.post("/plans", status_code=201)
async def create_plan(body: PlanIn,
                      ctx: TenantContext = Depends(require("dataset:read")),
                      session=Depends(get_session)):
    """Recommended action plan: named steps + the success metric that will
    judge it. Created PENDING — an approval request is opened automatically;
    outcomes are blocked until a human approves (the platform mandate)."""
    from ..models import Approval, MLModel

    ds = (await session.execute(select(Dataset).where(
        Dataset.id == body.metric_dataset_id,
        Dataset.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "Metric dataset not found")
    plan = MLModel(id=uuid7(), tenant_id=ctx.tenant_id, name=body.name,
                   kind="action_plan", dataset_id=ds.id, status="pending",
                   config={"steps": body.steps,
                           "metric": {"dataset_id": str(ds.id),
                                      "formula": body.metric_formula}})
    session.add(plan)
    await session.flush()
    session.add(Approval(id=uuid7(), tenant_id=ctx.tenant_id,
                         kind="action_plan", subject_id=str(plan.id),
                         note=f"Action plan '{body.name}' "
                              f"({len(body.steps)} steps)",
                         requested_by=ctx.user_id))
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="approval.request",
                       resource_type="action_plan", resource_id=str(plan.id))
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="plan.create",
                       resource_type="action_plan", resource_id=str(plan.id))
    await session.commit()
    return {"id": str(plan.id), "status": "pending",
            "note": "Awaiting human approval (catalog approvals queue). "
                    "Baseline is captured at approval time; report outcomes "
                    "after executing the steps."}


@router.get("/plans")
async def list_plans(ctx: TenantContext = Depends(require("dataset:read")),
                     session=Depends(get_session)):
    from ..models import MLModel

    rows = (await session.execute(select(MLModel).where(
        MLModel.tenant_id == ctx.tenant_id,
        MLModel.kind == "action_plan"))).scalars().all()
    return {"plans": [{"id": str(p.id), "name": p.name, "status": p.status,
                       "steps": p.config.get("steps"),
                       "metrics": p.metrics} for p in rows]}


@router.post("/plans/{plan_id}/outcome")
async def record_outcome(plan_id: str,
                         ctx: TenantContext = Depends(require("dataset:read")),
                         session=Depends(get_session)):
    """Closed-loop outcome tracking: recompute the plan's metric, compare to
    the approval-time baseline, record the delta. Refused while unapproved —
    no measurement theater for actions that were never authorized."""
    from datetime import datetime, timezone

    from ..models import MLModel
    from ..services import querysvc as _q

    plan = (await session.execute(select(MLModel).where(
        MLModel.id == plan_id, MLModel.tenant_id == ctx.tenant_id,
        MLModel.kind == "action_plan"))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, "Plan not found")
    if plan.status != "approved":
        raise HTTPException(403, "Plan is not approved — outcomes can only "
                                 "be recorded for human-approved plans.")
    metric = plan.config["metric"]
    ds = (await session.execute(select(Dataset).where(
        Dataset.id == metric["dataset_id"]))).scalar_one()
    current = (await _q.execute_formula(
        session, dataset_id=ds.id, current_import_id=ds.current_import_id,
        dataset_schema=ds.schema_def, formula=metric["formula"],
        filters=[]))["value"] or 0.0
    baseline = plan.metrics.get("baseline") or 0.0
    delta = round(current - baseline, 2)
    plan.metrics = {**plan.metrics, "outcome": current, "delta": delta,
                    "measured_at": datetime.now(timezone.utc).isoformat()}
    await audit.record(session, tenant_id=ctx.tenant_id,
                       actor_user_id=ctx.user_id, action="plan.outcome",
                       resource_type="action_plan", resource_id=str(plan.id))
    await session.commit()
    return {"baseline": baseline, "outcome": current, "delta": delta,
            "verdict": ("improved" if delta > 0 else
                        "declined" if delta < 0 else "unchanged")}


@router.get("/narrative")
async def orchestration_narrative(ctx: TenantContext = Depends(
        require("dataset:read")), session=Depends(get_session)):
    """Automated narrative generation (A3): the orchestrator's findings as
    a readable memo — same deterministic-template honesty as briefs."""
    o = await orchestrate(ctx, session)
    lines = [f"Analytics agents report — {len(o['agents_run'])} agents run.", ""]
    for name, ok in o["grounded"].items():
        if ok is False:
            lines.append(f"- {name}: no relevant data (skipped honestly).")
    for i, rec in enumerate(o["ranked_recommendations"][:5], 1):
        lines.append(f"{i}. [{rec['agent']}] {rec['action']} "
                     f"(score {rec['score']}).")
    lines.append("")
    lines.append("Every recommendation traces to a governed computation; "
                 "action requires human approval.")
    return {"text": "\n".join(lines)}
