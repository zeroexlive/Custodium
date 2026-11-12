"""TON outbound transaction record + indexing support models.

TON's account model needs two extra tables the block scanners do
not: a per-account transaction cursor (TON indexing polls account
histories, there is no block stream to walk) and a cache of
Jetton wallet addresses (deriving one requires executing the
Jetton master contract, so it is resolved once and kept).
"""

from __future__ import annotations

from django.db import models

from waas.modules.assets.models import Asset
from waas.modules.ledger.models import BalanceReservation
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Wallet


class TonTransaction(models.Model):
    class Status(models.TextChoices):
        CREATED = "created"
        RESERVED = "reserved"
        SIGNED = "signed"
        BROADCAST = "broadcast"
        CONFIRMED = "confirmed"
        REVERTED = "reverted"  # wallet tx found but execution failed / bounced
        FAILED = "failed"  # aborted locally; reservation released
        DROPPED = "dropped"  # broadcast outcome unknown; reservation HELD

    idempotency_key = models.CharField(max_length=200, unique=True)
    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="ton_transactions"
    )
    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.PROTECT, related_name="ton_transactions"
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="ton_transactions"
    )
    from_raw = models.CharField(max_length=80)  # wallet contract, raw form
    to_address = models.CharField(max_length=80)  # as supplied
    to_raw = models.CharField(max_length=80)
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    is_jetton = models.BooleanField(default=False)
    attached_ton_nano = models.BigIntegerField(default=0)  # jetton gas attach
    seqno = models.BigIntegerField(null=True, blank=True)
    valid_until = models.BigIntegerField(null=True, blank=True)
    external_message_hash = models.CharField(max_length=64, blank=True, db_index=True)
    tx_hash = models.CharField(max_length=64, blank=True, db_index=True)
    mc_block_seqno = models.BigIntegerField(null=True, blank=True)
    total_fees_nano = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CREATED
    )
    reservation = models.ForeignKey(
        BalanceReservation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ton_transactions",
    )
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ton_tx_amount_positive"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"TonTransaction({self.id}, {self.status}, seqno={self.seqno})"


class TonJettonAccount(models.Model):
    """A wallet's Jetton wallet contract for one Jetton master —
    resolved via the master's `get_wallet_address` and cached."""

    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="ton_jetton_accounts"
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="ton_jetton_accounts"
    )
    jetton_wallet_raw = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["wallet", "asset"], name="ton_jetton_account_unique"
            )
        ]


class TonScanCursor(models.Model):
    """Per-account indexing cursor: TON histories are polled per
    account and ordered by logical time (`lt`)."""

    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.PROTECT, related_name="ton_scan_cursors"
    )
    account_raw = models.CharField(max_length=80)
    last_lt = models.BigIntegerField(default=0)
    last_tx_hash = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["network", "account_raw"], name="ton_scan_cursor_unique"
            )
        ]
