@"
# Getting Started with InsightForge — Your First 30 Minutes

Welcome! This guide takes you from a fresh account to a live dashboard your
team can use. No SQL, no technical setup — if you can use a spreadsheet, you
can do everything here.

## 1. Create your organization (2 min)

Open InsightForge and choose **Register**. Pick your organization name, a
short URL slug, and a password (10+ characters). You are the **owner** — the
guided tour starts automatically and the Home page shows a checklist that
tracks your progress through everything below.

## 2. Bring in your data (5 min)

Go to **Sources**. Two easy paths:

* **Upload a file** — drag in a CSV or Excel export from your accounting,
  sales, or ops tool. InsightForge detects the columns and types
  automatically.
* **Connect a live database** — pick your platform's tile (PostgreSQL,
  MySQL, Supabase, Neon and more), fill in the connection details from your
  provider, and choose the table to sync. The connection is tested the
  moment you create it, and if something's wrong the error tells you exactly
  what to fix.

Your credentials are encrypted and never shown again — not even to you.

## 3. Trust what you imported (5 min)

Open **Datasets** and click your new dataset. Three things to notice:

* **Quality score** — a 0–100 rating of how clean this data is.
* **Quarantine** — rows that didn't fit (bad dates, text where numbers
  belong) are set aside with a reason, never silently deleted. Real business
  files almost always have a few — that's normal.
* **Recipes** — one-click cleanups (trim spaces, fix casing, fill blanks,
  convert types). Applying a recipe re-processes everything, rescues
  quarantined rows where possible, and re-scores the dataset. Watch the
  score climb.

Every number you'll see later can explain itself: the **lineage** view shows
where it came from and when, two clicks from any chart.

## 4. Build your first dashboard (5 min)

Go to **Dashboards** and use a **template** — pick *Sales Overview* or
*Finance Cash Flow*, point it at your dataset, and tell it which columns
hold the amount, the category, and the date. You get a full dashboard
instantly: KPIs, trends, breakdowns.

Then make it yours: add widgets (charts, tables, pivots, KPIs), drag to
rearrange, and **click any chart segment** to filter the whole dashboard —
click through to see the underlying rows.

## 5. Publish and share (3 min)

Dashboards start as **drafts** — your workspace. When it's ready, hit
**Publish**: that freezes a version your team sees, while you keep editing
the draft. Made a mess? Revert to any published version.

* **Invite teammates** — Members page; analysts can build, viewers can look.
* **Share externally** — create an expiring link for your accountant or
  investor. They see a read-only snapshot with its freshness and quality
  shown; the link dies on schedule, and you can revoke it anytime.

## 6. Let it run itself (5 min)

* **Scheduled syncs** — your connected sources refresh automatically on the
  schedule you choose.
* **Scheduled reports** — email a dashboard summary to anyone daily or
  weekly.
* **Alerts** — "email me if revenue drops below X" — set a threshold on any
  dataset and recipients get notified when it trips.
* **Insights** — on any dataset, forecast a trend or scan for anomalies.
  Forecasts are honest: they're labelled as forecasts and show their
  uncertainty band.

## Workspaces: one project, one place

Everything above lives in a **workspace** — a project folder holding its
sources, datasets, and dashboards together. Running analytics for two
clients or three departments? Create a workspace per project from the
switcher in the top bar; nothing mixes.

## If something goes wrong

* A connection fails → the error message says what to fix (wrong host,
  password, firewall) — follow it.
* Numbers look off → check the dataset's quality score and quarantine
  first; the answer is usually there.
* Locked out with MFA → use one of the recovery codes you saved when
  enabling it.
* Still stuck → contact your InsightForge partner contact; support can see
  system health and sync statuses, but never your business data.
"@ | Set-Content -Encoding utf8 docs\CUSTOMER-ONBOARDING.md