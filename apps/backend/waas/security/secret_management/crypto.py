"""Envelope-style symmetric encryption for recoverable API secrets.

HMAC request verification needs the *recoverable* secret, so a one-way hash
alone cannot work (see docs/api/authentication.md). Secrets are therefore
stored as Fernet ciphertext. In production the Fernet key is supplied via
WAAS_SECRET_ENCRYPTION_KEY and must be KMS/Vault-managed; the development
fallback derives a key from Django's SECRET_KEY and is NOT for production.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet() -> Fernet:
    configured = getattr(settings, "WAAS_SECRET_ENCRYPTION_KEY", "") or ""
    if configured:
        return Fernet(configured.encode() if isinstance(configured, str) else configured)
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(derived)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
