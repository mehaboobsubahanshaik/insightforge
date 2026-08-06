# MVP0 Verification — "is the foundation honestly done?"

Checklist executed against the running stack (all automated in CI except ⑤):

1. **One-command start** — `docker compose up --build` → web :8000,
   api :8001/docs, postgres healthy, migrations applied on boot. ✔
2. **Auth lifecycle** — register org → MFA enroll/confirm → logout → login
   (+ OTP) → refresh rotation → password reset via outbox token. ✔ tests
3. **Tenancy** — second org cannot read/guess first org's datasets,
   dashboards, insights (404s by RLS, not 403 leaks). ✔ tests
4. **Trust pipeline** — dirty CSV: typed, scored, quarantined visibly;
   recipe rescues rows; DQ history gains a point. ✔ tests
5. **Human pass** — tour, gallery tiles render with colors/glyphs, wizard
   docker-hint shows, loader animates, share page read-only. ✔ manual
6. **Live connectors** — Postgres 15 rows / MySQL 12 rows land; incremental
   picks up exactly the delta; guards refuse injection/SSRF hosts. ✔ tests
7. **Distribution** — publish freezes numbers; share link expires; report
   PDF lands in outbox; threshold alert fires once per breach. ✔ tests
8. **Ops** — suspended tenant blocked at login; ops console counts match. ✔
9. **Performance floor** (scripts/perf_smoke.py, dev laptop): 50k upload
   ≈5s, hydration p50 ≈120ms, 10 concurrent <2s, preview <30ms. ✔
