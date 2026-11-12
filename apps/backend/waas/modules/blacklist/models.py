"""Manual blacklist (docs/blacklist/manual-blacklist.md).

A manually curated list of addresses that must not receive funds. This
is NOT an AML/KYT/sanctions system and must never be described as one:
no external risk data, no scoring, no automated listing — every entry
is a deliberate human decision with a recorded reason. Entries are
never hard-deleted; they are soft-disabled for auditability.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class BlacklistEntry(models.Model):
    class Scope(models.TextChoices):
        PLATFORM = "platform", "Platform (applies to all tenants)"
        TENANT = "tenant", "Tenant (one organization)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, null=True, blank=True,
        related_name="blacklist_entries",
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, null=True, blank=True,
        related_name="blacklist_entries",
    )
    network = models.ForeignKey(
        "networks.BlockchainNetwork", on_delete=models.PROTECT, related_name="blacklist_entries"
    )
    address = models.CharField(max_length=128)  # raw, as entered
    normalized_address = models.CharField(max_length=128, db_index=True)
    reason = models.CharField(max_length=500)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="blacklist_entries"
    )
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "blacklist_entry"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(scope="platform", organization__isnull=True)
                    | models.Q(scope="tenant", organization__isnull=False)
                ),
                name="blacklist_scope_org_consistency",
            )
        ]

    def __str__(self) -> str:
        return f"BlacklistEntry({self.scope}, {self.network_id}, {self.normalized_address})"

    @property
    def is_effective(self) -> bool:
        return self.active and (self.expires_at is None or self.expires_at > timezone.now())
