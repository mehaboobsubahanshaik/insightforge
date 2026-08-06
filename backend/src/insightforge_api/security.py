"""Password hashing (scrypt), JWT (HS256 dev; OIDC adapter is roadmap debt),
opaque refresh tokens (hashed at rest), TOTP MFA."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

from .config import ACCESS_TOKEN_MINUTES, jwt_secret

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, key_hex = stored.split("$")
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(key.hex(), key_hex)
    except Exception:  # noqa: BLE001
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64(json.dumps({
        "iss": "insightforge", "sub": str(user_id), "tid": str(tenant_id), "role": role,
        "iat": now, "exp": now + ACCESS_TOKEN_MINUTES * 60,
    }).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = _b64(hmac.new(jwt_secret().encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_access_token(token: str) -> dict | None:
    try:
        header, payload, sig = token.split(".")
        expected = _b64(
            hmac.new(jwt_secret().encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(_unb64(payload))
        if claims.get("exp", 0) < time.time():
            return None
        return claims
    except Exception:  # noqa: BLE001
        return None


def new_opaque_token() -> tuple[str, str]:
    """Returns (raw, sha256) — raw goes to the client, only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def sha256_of(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def totp_now(secret: str, offset: int = 0) -> str:
    import pyotp

    return pyotp.TOTP(secret).at(time.time() + offset * 30)


def totp_verify(secret: str, code: str) -> bool:
    import pyotp

    return pyotp.TOTP(secret).verify(code, valid_window=1)


def new_totp_secret() -> str:
    import pyotp

    return pyotp.random_base32()
