from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

ALLOWED_SCOPES = {
    "read",
    "wallets:read", "wallets:write",
    "addresses:read", "addresses:write",
    "transactions:read",
    "deposits:read",
    "withdrawals:read", "withdrawals:write",
    "sweeps:read", "sweeps:write",
    "webhooks:manage",
    "assets:read",
}


class ApiKey(models.Model):
    """Machine credential for one project/environment.

    The secret is stored ONLY as Fernet ciphertext (recoverable, needed for
    HMAC verification — see docs/api/authentication.md). It is returned in
    plaintext exactly once, at creation/rotation. Ciphertext must never be
    exposed through any API schema.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=150)
    key_id = models.CharField(max_length=64, unique=True, db_index=True)
    secret_ciphertext = models.TextField()
    scopes = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    ip_allowlist = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_api_keys"
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    rotated_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="rotations"
    )

    class Meta:
        db_table = "api_credentials_api_key"

    def __str__(self) -> str:
        return f"{self.key_id} ({self.name})"

    @property
    def is_usable(self) -> bool:
        if self.status != self.Status.ACTIVE:
            return False
        return not (self.expires_at and self.expires_at <= timezone.now())

    @classmethod
    def generate_key_id(cls, environment: str) -> str:
        prefix = "ck_live" if environment == "production" else "ck_test"
        return f"{prefix}_{secrets.token_hex(10)}"

    @staticmethod
    def generate_secret() -> str:
        return secrets.token_urlsafe(32)

    def revoke(self) -> None:
        self.status = self.Status.REVOKED
        self.revoked_at = timezone.now()
        self.save(update_fields=["status", "revoked_at"])


class UsedNonce(models.Model):
    """Replay protection: a (api_key, nonce) pair may be used exactly once."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_key = models.ForeignKey(ApiKey, on_delete=models.CASCADE, related_name="used_nonces")
    nonce = models.CharField(max_length=128)
    used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "api_credentials_used_nonce"
        constraints = [
            models.UniqueConstraint(fields=["api_key", "nonce"], name="uniq_nonce_per_api_key")
        ]
