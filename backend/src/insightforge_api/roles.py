"""RBAC. Roles are additive tiers; permissions gate every mutating endpoint
and all admin reads. Enforcement is server-side only — the UI merely hides."""

TENANT_OWNER = "tenant_owner"
TENANT_ADMIN = "tenant_admin"
ANALYST = "analyst"
VIEWER = "viewer"

DATA_ADMIN = "data_admin"
BI_DEVELOPER = "bi_developer"
EXECUTIVE_VIEWER = "executive_viewer"
BILLING_ADMIN = "billing_admin"
SECURITY_AUDITOR = "security_auditor"

ROLES = [TENANT_OWNER, TENANT_ADMIN, DATA_ADMIN, BI_DEVELOPER, ANALYST,
         EXECUTIVE_VIEWER, BILLING_ADMIN, SECURITY_AUDITOR, VIEWER]
ADMINS = {TENANT_OWNER, TENANT_ADMIN}
DATA_ADMINS = ADMINS | {DATA_ADMIN}
BUILDERS = DATA_ADMINS | {ANALYST, BI_DEVELOPER}
EVERYONE = BUILDERS | {VIEWER, EXECUTIVE_VIEWER, BILLING_ADMIN,
                       SECURITY_AUDITOR}

PERMISSIONS = {
    "workspace:manage": ADMINS,
    "dataset:create": BUILDERS,
    "dataset:read": EVERYONE - {BILLING_ADMIN},
    "dataset:export": BUILDERS | {VIEWER, EXECUTIVE_VIEWER},
    "measure:create": BUILDERS,
    "dashboard:create": BUILDERS,
    "dashboard:read": EVERYONE - {BILLING_ADMIN, SECURITY_AUDITOR},
    "connection:manage": DATA_ADMINS,
    "connection:read": BUILDERS,
    "member:manage": ADMINS,
    "audit:read": ADMINS | {SECURITY_AUDITOR},
    "usage:read": ADMINS | {BILLING_ADMIN},
    "tenant:manage": {TENANT_OWNER},
}


def role_allows(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())
