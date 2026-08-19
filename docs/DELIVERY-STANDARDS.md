# Delivery Standards — Definition of Ready / Done, increment report

## Definition of Ready (a story may enter a build phase when…)
1. Persona + job named; acceptance criteria in Given/When/Then.
2. Security surface identified (authz scope, tenant isolation, data class).
3. Test shape known (what proves it); rollback path stated for schema work.
4. Dependencies (migrations, deps, external creds) listed; external ones
   go to Bucket B, never faked.

## Definition of Done (nothing is "done" without…)
1. Code + migration merged behind the proof gate: full pytest green in the
   container, ruff clean.
2. New behavior covered by at least one test asserting the HAPPY path and
   one asserting the REFUSAL path (422/403/401), plus audit where relevant.
3. Delivered docs updated (register, verification, release notes).
4. Validation checklist a human can run in the product.
5. Overclaims forbidden: partials named in GAP-REGISTER.md.

## Increment report template (per §16 of the master prompt)
Scope · files changed · DB changes (migration id + downgrade) · API
changes · security implications · tests added + counts · quality gates
(pytest/ruff/CI) · known limitations · deployment (copy list + rebuild) ·
rollback (git revert + alembic downgrade) · next increment.
Phases MVP1–R18 in COMPLETION-VERIFICATION.md instantiate this.
