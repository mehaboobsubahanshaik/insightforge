"""Domain analytics agents (MVP6 A1): deterministic analysis pipelines over
the governed primitives — every agent finding traces to a computation, every
agent refuses domains it can't ground (no relevant columns = say so).
Agents OBSERVE and RECOMMEND only; action requires the human approval
workflow (A2) per the platform mandate."""


from . import narrative, prepsvc

DOMAIN_HINTS = {
    "finance": ("revenue", "amount", "total", "cost", "price", "invoice"),
    "sales": ("deal", "pipeline", "quota", "sales", "order", "customer"),
    "marketing": ("campaign", "spend", "click", "lead", "impression",
                  "channel"),
    "operations": ("inventory", "shipment", "delivery", "backlog", "sla",
                   "ticket", "quantity"),
}


def _relevant(ds, hints) -> list[str]:
    return [c["name"] for c in ds.schema_def
            if any(h in c["name"].lower() for h in hints)
            and c["inferred_type"] in ("number", "integer")]


async def _domain_agent(session, datasets, domain: str) -> dict:
    hints = DOMAIN_HINTS[domain]
    findings, recs, analyzed = [], [], []
    for ds in datasets:
        cols = _relevant(ds, hints)
        date_cols = [c["name"] for c in ds.schema_def
                     if c["inferred_type"] in ("date", "timestamp")]
        if not cols or not date_cols:
            continue
        driver = next((c["name"] for c in ds.schema_def
                       if c["inferred_type"] == "text"
                       and not c["name"].lower().endswith("id")), None)
        for col in cols[:2]:
            analyzed.append(f"{ds.name}.{col}")
            pop = await narrative.pop_kpi(session, ds, f"sum({col})",
                                          date_cols[0], driver)
            if pop["previous"] or pop["current"]:
                sent = (f"{col}: {narrative._fmt(pop['current'])}, "
                        f"{pop['pct']} vs prior window."
                        + narrative.driver_sentence(pop["change"],
                                                    pop["drivers"],
                                                    driver or ""))
                sev = ("high" if pop["previous"]
                       and abs(pop["change"]) > abs(pop["previous"]) * .2
                       else "info")
                findings.append({"severity": sev, "finding": sent,
                                 "dataset": ds.name, "metric": col,
                                 "windows": pop["windows"]})
                if sev == "high" and pop["drivers"]:
                    top = pop["drivers"][0]
                    direction = "decline" if pop["change"] < 0 else "growth"
                    recs.append({
                        "action": f"Review {driver}='{top['group']}' — it "
                                  f"drives the {direction} in {col}",
                        "metric": f"{ds.name}.{col}",
                        "expected_impact": abs(top["delta"]),
                        "confidence": "high",
                        "grounded_in": pop["windows"]})
    if not analyzed:
        return {"agent": domain, "grounded": False,
                "message": f"No {domain}-relevant numeric+date columns found "
                           f"(looked for: {', '.join(hints)}). Nothing to "
                           "analyze — refusing rather than guessing."}
    return {"agent": domain, "grounded": True, "analyzed": analyzed,
            "findings": findings, "recommendations": recs}


async def data_quality_agent(session, datasets) -> dict:
    findings, recs = [], []
    for ds in datasets:
        if (ds.quality_score or 100) < 95 or (ds.quarantined_count or 0):
            findings.append({"severity": "warn", "dataset": ds.name,
                             "finding": f"quality {ds.quality_score}/100, "
                                        f"{ds.quarantined_count or 0} rows "
                                        "quarantined"})
        for sug in (await prepsvc.suggest(session, ds))[:3]:
            recs.append({"action": f"{sug['op']} on {ds.name}.{sug['column']}",
                         "rationale": sug["reason"],
                         "expected_impact": sug["effect"],
                         "confidence": "high"})
    return {"agent": "data_quality", "grounded": True,
            "findings": findings, "recommendations": recs,
            "note": "Apply any fix via the dataset's Suggest-fixes panel — "
                    "agents never modify data themselves."}


async def executive_briefing_agent(session, tenant_id, dashboards,
                                   ds_by_id) -> dict:
    briefs = []
    for d in dashboards[:3]:
        b = await narrative.executive_brief(
            session, d.name, d.widgets,
            {k: v for k, v in ds_by_id.items()
             if k in {w["dataset_id"] for w in d.widgets}})
        briefs.append({"dashboard": d.name, "text": b["text"]})
    return {"agent": "executive_briefing", "grounded": True,
            "briefs": briefs,
            "findings": [], "recommendations": []}


AGENTS = ("finance", "sales", "marketing", "operations", "data_quality",
          "executive_briefing")


async def run_agent(session, tenant_id, name: str, datasets, dashboards,
                    ds_by_id) -> dict:
    if name in DOMAIN_HINTS:
        return await _domain_agent(session, datasets, name)
    if name == "data_quality":
        return await data_quality_agent(session, datasets)
    if name == "executive_briefing":
        return await executive_briefing_agent(session, tenant_id,
                                              dashboards, ds_by_id)
    raise ValueError(f"unknown agent {name}")
