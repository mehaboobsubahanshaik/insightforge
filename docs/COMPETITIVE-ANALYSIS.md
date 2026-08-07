| | Zoho Analytics | Power BI | Tableau | Metabase | Superset | Looker Studio | **InsightForge** |
|---|---|---|---|---|---|---|---|
| SMB pricing fit | ✔ | partial | ✘ (per-seat $$) | ✔ (OSS) | ✔ (OSS) | ✔ (free) | ✔ |
| Setup burden | medium | high | high | medium | high (infra-heavy) | low | **low (one compose command)** |
| Data quality surfacing | weak | add-on | prep add-on | none | none | none | **core: score+quarantine+recipes** |
| Lineage for end users | no | enterprise tier | catalog add-on | no | partial (SQL-level) | no | **2 clicks from any chart** |
| Governed formulas | partial | DAX (expert) | calc fields (expert) | SQL (expert) | SQL (expert) | limited | **small governed language** |
| Trust telemetry on shares | no | no | no | no | no | no | **readout on every snapshot** |
| Honest forecasting UX | black-box | black-box | black-box | none | none | none | **labelled + banded** |

Gap analysis vs the two added: **Tableau** wins on visualization depth and an
analyst ecosystem we don't contest — its per-seat pricing and prep/catalog
add-on model is precisely the SMB mismatch we exploit. **Superset** wins on
extensibility for engineering teams; it presumes SQL fluency and self-hosted
ops, both absent in our personas — one compose command vs a platform team.

Positioning sentence: *"Zoho shows you charts; InsightForge shows you charts
you can defend in a bank meeting."*

Threats: incumbents adding "quality badges" (mitigate: depth — recipes,
quarantine, lineage are structural, not cosmetic); LLM-BI startups
(mitigate: SMBs punish hallucinated numbers; our honesty stance is the moat).
