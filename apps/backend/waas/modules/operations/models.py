"""Phase 9 financial operations: withdrawal policy, the
withdrawal request lifecycle, approvals, and reconciliation halts.

The chain modules (Phases 4–8) move value; this module owns the
*business* lifecycle around them, per the Phase 0 API design:
`pending_policy → approved → signing → broadcast → confirming →
completed | failed | rejected`. Business approval quorum (here)
is deliberately distinct from the MPC signing threshold.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from waas.modules.assets.models import Asset
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet


class WithdrawalPolicy(models.Model):
    """Per-project withdrawal policy; a row with `asset = NULL` is
    the project default, an asset row overrides it for that asset.

    Amounts are integer base units of the relevant asset. A NULL
    limit means "no limit". `service_fee_flat` is charged in the
    withdrawn asset (see services for the accounting).
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="withdrawal_policies"
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="withdrawal_policies",
    )
    max_single_amount = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True
    )
    daily_limit = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True
    )
    approvals_required = models.PositiveSmallIntegerField(default=1)
    auto_approve_below = models.DecimalField(
        max_digits=78, decimal_places=0, default=0
    )  # amounts <= this need no approvals
    service_fee_flat = models.DecimalField(
        max_digits=78, decimal_places=0, default=0
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "asset"], name="withdrawal_policy_unique"
            )
        ]


class WithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING_POLICY = "pending_policy"
        APPROVED = "approved"
        REJECTED = "rejected"
        SIGNING = "signing"
        BROADCAST = "broadcast"
        CONFIRMING = "confirming"
        COMPLETED = "completed"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="withdrawal_requests"
    )
    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="withdrawal_requests"
    )
    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.PROTECT, related_name="withdrawal_requests"
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="withdrawal_requests"
    )
    destination_address = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    external_reference = models.CharField(max_length=200, blank=True)
    idempotency_key = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING_POLICY
    )
    status_reason = models.TextField(blank=True)
    requested_by_type = models.CharField(max_length=16, default="api")  # api|dashboard
    requested_by_id = models.CharField(max_length=64, blank=True)
    approvals_required = models.PositiveSmallIntegerField(default=1)
    service_fee = models.DecimalField(max_digits=78, decimal_places=0, default=0)
    service_fee_charged = models.BooleanField(default=False)
    # Link to the chain-module transaction that executed this request.
    chain_family = models.CharField(max_length=16, blank=True)  # evm|tron|solana|ton
    chain_tx_id = models.BigIntegerField(null=True, blank=True)
    chain_tx_hash = models.CharField(max_length=128, blank=True)
    actual_fee = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True
    )
    fee_asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fee_for_withdrawals",
    )
    refunded_amount = models.DecimalField(max_digits=78, decimal_places=0, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "idempotency_key"],
                name="withdrawal_request_idempotency_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="withdrawal_request_amount_positive"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"WithdrawalRequest({self.id}, {self.status})"


class WithdrawalApproval(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved"
        REJECTED = "rejected"

    request = models.ForeignKey(
        WithdrawalRequest, on_delete=models.CASCADE, related_name="approvals"
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="withdrawal_approvals"
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request", "approver"], name="withdrawal_approval_once_per_user"
            )
        ]


class ReconciliationHalt(models.Model):
    """A fail-closed halt on outflows for a network whose latest
    reconciliation showed an unexplained discrepancy. Raised and
    cleared by the `run_reconciliation` command; while active,
    new withdrawals on the network are refused."""

    network = models.OneToOneField(
        BlockchainNetwork, on_delete=models.CASCADE, related_name="reconciliation_halt"
    )
    active = models.BooleanField(default=False)
    reason = models.TextField(blank=True)
    raised_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
