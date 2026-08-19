# Product Backlog — journeys, jobs, stories

## Jobs-to-be-done
1. "Show me the truth about my business without hiring an analyst."
2. "Let my team share one set of certified numbers."
3. "Put analytics inside MY product without leaking customers' data."
4. "Pass my auditor's questions without a war room."
5. "Tell me what to do next — but never do it without me."

## Pain points (SMB research assumptions to validate)
Spreadsheet chaos · numbers disagree between tools · BI tools priced/staffed
for enterprises · AI answers nobody trusts · embedded analytics leaks fear.

## Sample journeys
- Priya (owner): signup → guided onboarding → CSV upload → quality score
  explains itself → first dashboard + Ask → weekly brief email. TTFD < 1h.
- Sana (vendor PM): connect API → template child tenant → mint edit token →
  builder in her app → usage metering on her invoice.

## Epic backlog (post-1.0, priority order)
E1 Mobile-responsive polish + geo/cohort visuals — stories: geo choropleth
   widget (AC: renders 30 countries < 1s), cohort retention grid.
E2 Live connector activations — per-vendor OAuth app setup guides (AC: one
   real QuickBooks tenant syncing nightly).
E3 DuckDB read path (STORAGE-EVALUATION step 1) (AC: 10M-row aggregate
   < 500ms p95).
E4 Next.js frontend migration, screen-by-screen (AC: parity checklist per
   screen, zero API changes).
E5 Load-test suite (k6) + published NFR evidence.
Story format everywhere: As <persona> I want <capability> so that <job>;
AC = Given/When/Then; every story lands with tests (house rule).
