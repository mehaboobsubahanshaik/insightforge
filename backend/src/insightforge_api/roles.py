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
DATA_ENGINEER = "data_engineer"
BUSINESS_USER = "business_user"
EXTERNAL_VIEWER = "external_viewer"
SUPPORT_OPERATOR = "support_operator"
SERVICE_ACCOUNT = "service_account"

ROLES = [TENANT_OWNER, TENANT_ADMIN, DATA_ADMIN, DATA_ENGINEER,
         BI_DEVELOPER, ANALYST, BUSINESS_USER, EXECUTIVE_VIEWER,
         EXTERNAL_VIEWER, BILLING_ADMIN, SECURITY_AUDITOR,
         SUPPORT_OPERATOR, SERVICE_ACCOUNT, VIEWER]
ADMINS = {TENANT_OWNER, TENANT_ADMIN}
DATA_ADMINS = ADMINS | {DATA_ADMIN, DATA_ENGINEER}
BUILDERS = DATA_ADMINS | {ANALYST, BI_DEVELOPER, SERVICE_ACCOUNT}
READERS = {VIEWER, BUSINESS_USER, EXECUTIVE_VIEWER, EXTERNAL_VIEWER}
EVERYONE = BUILDERS | READERS | {BILLING_ADMIN, SECURITY_AUDITOR,
                                 SUPPORT_OPERATOR}

PERMISSIONS = {
    "workspace:manage": ADMINS,
    "dataset:create": BUILDERS,
    "dataset:read": EVERYONE - {BILLING_ADMIN, EXTERNAL_VIEWER,
                                 SUPPORT_OPERATOR},
    "dataset:export": BUILDERS | {VIEWER, BUSINESS_USER,
                                   EXECUTIVE_VIEWER},
    "measure:create": BUILDERS,
    "dashboard:create": BUILDERS,
    "dashboard:read": EVERYONE - {BILLING_ADMIN, SECURITY_AUDITOR,
                                   SUPPORT_OPERATOR},
    "connection:manage": DATA_ADMINS,
    "connection:read": BUILDERS,
    "member:manage": ADMINS,
    "audit:read": ADMINS | {SECURITY_AUDITOR, SUPPORT_OPERATOR},
    "usage:read": ADMINS | {BILLING_ADMIN, SUPPORT_OPERATOR},
    "tenant:manage": {TENANT_OWNER},
}


def role_allows(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())
