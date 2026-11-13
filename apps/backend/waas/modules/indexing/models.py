"""Indexing state (Phase 5): per-network scan cursor, recent block
hashes (the reorg evidence trail), and observed deposits.

A deposit moves through a two-stage ledger lifecycle:

    detected ──(DEPOSIT_OBSERVED entry)──▶ pending
    pending  ──(DEPOSIT_CREDIT entry, at the network's
                confirmation threshold)──▶ credited
    any      ──(reorg removes its block; entries reversed)──▶
                reorged_out

A reappearing transaction in the new fork is a NEW deposit row:
uniqueness includes the block hash, so a replayed identical block
is idempotent while a reorged-in transaction starts a fresh,
correct lifecycle.
"""

from __future__ import annotations

from django.db import models

from waas.modules.assets.models import Asset
from waas.modules.ledger.models import JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address, Wallet


class ChainCursor(models.Model):
    """Where the scanner has got to on one network."""

    network = models.OneToOneField(
        BlockchainNetwork, on_delete=models.CASCADE, related_name="index_cursor"
    )
    last_block_number = models.BigIntegerField(default=-1)  # -1 = nothing scanned
    last_block_hash = models.CharField(max_length=66, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class ScannedBlock(models.Model):
    """Recent block hashes per network — the ancestor evidence the
    reorg walk-back compares against the live chain. Pruned to a
    trailing window by the scanner."""

    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.CASCADE, related_name="scanned_blocks"
    )
    number = models.BigIntegerField()
    hash = models.CharField(max_length=66)
    parent_hash = models.CharField(max_length=66, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["network", "number"], name="uniq_scanned_block_per_network"
            )
        ]
        ordering = ["network", "number"]


class ObservedDeposit(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"  # observed; DEPOSIT_OBSERVED posted
        CREDITED = "credited"  # confirmation threshold met; DEPOSIT_CREDIT posted
        REORGED_OUT = "reorged_out"  # block orphaned; entries reversed

    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.PROTECT, related_name="observed_deposits"
    )
    address = models.ForeignKey(
        Address, on_delete=models.PROTECT, related_name="observed_deposits"
    )
    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="observed_deposits"
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="observed_deposits"
    )
    tx_hash = models.CharField(max_length=66, db_index=True)
    # Position of the deposit within its block: the log index for
    # token transfers, the transaction index for native transfers.
    occurrence = models.IntegerField()
    from_address = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    block_number = models.BigIntegerField()
    block_hash = models.CharField(max_length=66)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # A deposit whose sender is on the manual blacklist is observed
    # and held in pending for manual review — never auto-credited.
    held = models.BooleanField(default=False)
    hold_reason = models.CharField(max_length=200, blank=True)
    observed_entry = models.ForeignKey(
        JournalEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name="deposits_observed",
    )
    credit_entry = models.ForeignKey(
        JournalEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name="deposits_credited",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["network", "tx_hash", "occurrence", "block_hash"],
                name="uniq_deposit_event_per_block",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="deposit_amount_positive"
            ),
        ]
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"ObservedDeposit({self.id}, {self.network.slug}, {self.status})"


class DepositPolicy(models.Model):
    """Per-(project, asset) deposit rules (2026-11-13).

    `min_amount` is the smallest single deposit, in integer base
    units, that is credited on its own. Deposits below it are
    HELD (observed, never silently dropped) and are credited
    together once the held total for the same wallet + asset
    reaches the minimum — the standard "small deposits
    accumulate" behaviour. Zero disables the minimum. There is
    deliberately NO maximum: capping deposits would strand user
    funds on-chain, so the platform accepts and credits any
    amount at or above the minimum.
    """

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="deposit_policies"
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, related_name="deposit_policies"
    )
    min_amount = models.DecimalField(max_digits=78, decimal_places=0, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "asset"], name="uniq_deposit_policy_per_asset"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"DepositPolicy({self.project_id}, {self.asset_id}, min={self.min_amount})"
