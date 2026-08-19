# Load tests (k6)
1. Install k6 (winget install k6 / brew install k6).
2. Log in, grab an access token and a dataset id.
3. RATE_LIMIT_PER_MIN=100000 in compose for the run (limits are for
   production, not for measuring capacity).
4. k6 run -e BASE=http://localhost:8000 -e TOKEN=... -e DS=... k6-smoke.js
Thresholds mirror docs/NFR-TARGETS.md — a red run is an honest evidence gap.
