# Data Quality Rule Catalog
| ID | Rule | Action | Where |
|---|---|---|---|
| R001 | Missing required value | quarantine row | ingest |
| R002 | Duplicate row | quarantine duplicate | ingest |
| R003 | Type mismatch (expected number/date) | quarantine + reason | ingest |
| R004 | Whitespace padding | auto-trim at load | ingest |
| R005 | Inconsistent casing | suggest uppercase/lowercase | prepsvc |
| R006 | Currency symbols in numerics | suggest strip_non_numeric | prepsvc |
| R007 | Missing values cluster | suggest fill strategy | prepsvc |
| R008 | Statistical outlier (z>3) | ADVISORY only, never auto | prepsvc R13 |
| R009 | Freshness beyond SLA | alert (governance.alerts) | scheduler R7 |
| R010 | Quality score below floor | alert | scheduler R7 |
| R011 | Schema drift breaking references | drift-report finding | R13 |
Every quarantined row keeps its reason; rescue via recipes re-scores.
