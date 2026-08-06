# Domain Model

Tenant 1—n Membership n—1 User; Tenant 1—n Workspace; Workspace 1—n
{Connection, Dataset, Dashboard}. Dataset 1—n DatasetRow (per import
generation), 1—n DQResult, 1—n DQHistory, 1—n Measure. Dashboard 1—n
DashboardVersion, 1—n Comment, 1—n ShareLink, 1—n ReportSchedule,
1—n AlertRule (via dataset). Every row carries tenant_id; PostgreSQL RLS
enforces isolation below the ORM (see THREAT-MODEL).

**Workspace = the project folder.** All documents for one initiative — its
source connections, the datasets they land, and the dashboards built on them
— live under one workspace. The UI's workspace switcher scopes every list;
creation flows default into the active workspace. Deleting is deliberately
absent in MVP (archive semantics come with retention policies).

Import generations: every ingest/recipe application writes a fresh
`import_id` set of rows and repoints `current_import_id` — queries are
snapshot-consistent, history is auditable, and lineage hops are appended.

Key invariants (enforced in code + tests):
* A row is never deleted by cleaning — it is superseded by a new generation.
* Published dashboard versions are frozen JSON snapshots (immutable).
* Share links expose only published snapshots, never live queries.
* recipe/apply re-processes ALL rows incl. quarantined (that's the rescue path).
