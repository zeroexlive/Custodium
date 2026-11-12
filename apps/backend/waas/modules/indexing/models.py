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
