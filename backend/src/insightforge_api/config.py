"""Environment configuration (12-factor). Everything has a safe dev default;
production values come from the environment / secret store."""

import base64
import hashlib
import os


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or os.environ.get(
        "ALEMBIC_DSN", "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/insightforge"
    )


def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "local-dev-secret-change-me")


def encryption_key() -> bytes:
    """Fernet key for the credential vault. In dev it is derived from
    JWT_SECRET so the stack boots with zero setup; in production set
    APP_ENCRYPTION_KEY explicitly (and rotate via re-encryption)."""
    raw = os.environ.get("APP_ENCRYPTION_KEY")
    if raw:
        return raw.encode()
    return base64.urlsafe_b64encode(hashlib.sha256(jwt_secret().encode()).digest())


ACCESS_TOKEN_MINUTES = 30
REFRESH_TOKEN_DAYS = 14
