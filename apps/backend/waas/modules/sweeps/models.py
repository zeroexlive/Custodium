"""Phase 10 sweeps: the registered resolver endpoint (the ONLY
source of sweep destinations), its immutable change history,
per-sweep destination snapshots, and the sweep lifecycle.

Binding rules (docs/api/sweep-resolver.md, ADR 0006):
- The endpoint URL lives ONLY in PostgreSQL, one row per project.
- A sweep's destination comes from a fresh resolution at sweep
  time, persisted as an append-only snapshot before any signing.
- Snapshots have no update path.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from waas.modules.assets.models import Asset
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet


class SweepDestinationEndpoint(models.Model):
    """The tenant-registered resolver endpoint for one project
    (the project row fixes tenant + environment scope)."""

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="sweep_endpoint"
    )
    url = models.URLField(max_length=500)
    enabled = models.BooleanField(default=True)
    signing_secret_ciphertext = models.TextField(blank=True)  # Fernet; never exposed
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sweep_endpoint_updates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SweepEndpointHistory(models.Model):
    """Append-only record of endpoint registration changes. URLs
    are stored as hashes: the audit trail proves what changed
    without duplicating the live value."""

    endpoint = models.ForeignKey(
        SweepDestinationEndpoint, on_delete=models.CASCADE, related_name="history"
    )
    actor_id = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=32)  # registered|updated|disabled|enabled
    previous_url_hash = models.CharField(max_length=64, blank=True)
    new_url_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class SweepPolicy(models.Model):
    """Per-project sweep policy: sweep the wallet scope's
    available balance down to `leave_behind`, only when the
    sweepable amount reaches `min_sweep_threshold`."""

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="sweep_policy"
    )
    min_sweep_threshold = models.DecimalField(max_digits=78, decimal_places=0, default=0)
    leave_behind = models.DecimalField(max_digits=78, decimal_places=0, default=0)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class AutoSweepRule(models.Model):
    """Trigger layer for sweeping (the policy above decides HOW
    MUCH a sweep moves; this decides WHEN one is created).

    When the wallet scope's available balance for (network,
    asset) reaches `threshold_amount`, the `run_auto_sweeps`
    command creates a sweep through the ordinary `create_sweep`
    path — resolver snapshot, blacklist/policy checks, approval
    quorum and the sweep policy's threshold/leave-behind all
    still apply downstream. At most one open auto-created sweep
    per rule at a time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="auto_sweep_rules"
    )
    wallet = models.ForeignKey(
        "wallets.Wallet", on_delete=models.CASCADE, related_name="auto_sweep_rules"
    )
    network = models.ForeignKey(
        "networks.BlockchainNetwork", on_delete=models.PROTECT, related_name="auto_sweep_rules"
    )
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.PROTECT, related_name="auto_sweep_rules"
    )
    threshold_amount = models.DecimalField(max_digits=78, decimal_places=0)
    enabled = models.BooleanField(default=True)
    trigger_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="auto_sweep_rules"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sweeps_auto_sweep_rule"
        constraints = [
            models.UniqueConstraint(
                fields=["wallet", "network", "asset"],
                name="uniq_auto_sweep_rule_wallet_network_asset",
            )
        ]

    def __str__(self) -> str:
        return f"AutoSweepRule(wallet={self.wallet_id}, threshold={self.threshold_amount})"


class Sweep(models.Model):
    class Status(models.TextChoices):
        CREATED = "created"
        RESOLVING = "resolving"
        RESOLUTION_FAILED = "resolution_failed"
        RESOLVED = "resolved"
        POLICY_DENIED = "policy_denied"
        AWAITING_APPROVAL = "awaiting_approval"
        REJECTED = "rejected"
        SIGNING = "signing"
        BROADCAST = "broadcast"
        CONFIRMING = "confirming"
        COMPLETED = "completed"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="sweeps"
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="sweeps")
    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.PROTECT, related_name="sweeps"
    )
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="sweeps")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.CREATED
    )
    status_reason = models.TextField(blank=True)
    amount = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True
    )
    external_reference = models.CharField(max_length=200, blank=True)
    idempotency_key = models.CharField(max_length=200)
    requested_by_type = models.CharField(max_length=16, default="api")
    requested_by_id = models.CharField(max_length=64, blank=True)
    approvals_required = models.PositiveSmallIntegerField(default=0)
    chain_family = models.CharField(max_length=16, blank=True)
    chain_tx_id = models.BigIntegerField(null=True, blank=True)
    chain_tx_hash = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "idempotency_key"],
                name="sweep_idempotency_unique",
            )
        ]


class SweepApproval(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved"
        REJECTED = "rejected"

    sweep = models.ForeignKey(Sweep, on_delete=models.CASCADE, related_name="approvals")
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sweep_approvals"
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sweep", "approver"], name="sweep_approval_once_per_user"
            )
        ]


class ResolvedDestinationSnapshot(models.Model):
    """The immutable record of one resolution: exactly what the
    endpoint returned (hashed), what it parsed to, and for which
    sweep. Created once; updates are refused at the model layer."""

    sweep = models.OneToOneField(
        Sweep, on_delete=models.CASCADE, related_name="destination_snapshot"
    )
    destination_address = models.CharField(max_length=128)
    normalized_address = models.CharField(max_length=128)
    endpoint_url_hash = models.CharField(max_length=64)
    request_id = models.CharField(max_length=64)
    raw_body_sha256 = models.CharField(max_length=64)
    resolver_version = models.PositiveSmallIntegerField(default=1)
    resolved_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is not None and ResolvedDestinationSnapshot.objects.filter(
            pk=self.pk
        ).exists():
            raise ValueError("destination snapshots are immutable")
        return super().save(*args, **kwargs)
