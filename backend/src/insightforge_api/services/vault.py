"""Connector credential vault: Fernet (AES-128-CBC + HMAC) encryption at
rest. Decrypted only at the moment a connector call needs the secret; never
returned by any API, never logged, excluded from diagnostics."""

import json

from cryptography.fernet import Fernet

from ..config import encryption_key


def encrypt_credentials(credentials: dict) -> str:
    return Fernet(encryption_key()).encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(blob: str) -> dict:
    if not blob:
        return {}
    return json.loads(Fernet(encryption_key()).decrypt(blob.encode()))
