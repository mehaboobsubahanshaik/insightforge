"""RBAC. Roles are additive tiers; permissions gate every mutating endpoint
and all admin reads. Enforcement is server-side only — the UI merely hides."""

TENANT_OWNER = "tenant_owner"
TENANT_ADMIN = "tenant_admin"
ANALYST = "analyst"
VIEWER = "viewer"

ROLES = [TENANT_OWNER, TENANT_ADMIN, ANALYST, VIEWER]
ADMINS = {TENANT_OWNER, TENANT_ADMIN}
BUILDERS = ADMINS | {ANALYST}
EVERYONE = BUILDERS | {VIEWER}

PERMISSIONS = {
    "workspace:manage": ADMINS,
    "dataset:create": BUILDERS,
    "dataset:read": EVERYONE,
    "dataset:export": EVERYONE,
    "measure:create": BUILDERS,
    "dashboard:create": BUILDERS,
    "dashboard:read": EVERYONE,
    "connection:manage": ADMINS,
    "connection:read": BUILDERS,
    "member:manage": ADMINS,
    "audit:read": ADMINS,
    "usage:read": ADMINS,
    "tenant:manage": {TENANT_OWNER},
}


def role_allows(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())
