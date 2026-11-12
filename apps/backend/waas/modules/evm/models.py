"""EVM transaction pipeline records (Phase 4).

One row tracks one outbound EVM transaction through the withdrawal
pipeline (reserve → sign → broadcast → confirm → settle). The row's
idempotency key is the pipeline's anchor: re-entering the pipeline
with the same key returns the existing row instead of reserving or
broadcasting twice. Ledger effects themselves live in the ledger
module; this row references the reservation it holds.
"""

from __future__ import annotations

from django.db import models

from waas.modules.assets.models import Asset
from waas.modules.ledger.models import BalanceReservation
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Wallet


class EvmTransaction(models.Model):
    class Status(models.TextChoices):
        CREATED = "created"
        RESERVED = "reserved"
        SIGNED = "signed"
        BROADCAST = "broadcast"
        CONFIRMED = "confirmed"  # mined successfully; ledger settled
        REVERTED = "reverted"  # mined but reverted; reservation released
        FAILED = "failed"  # aborted before broadcast; reservation released
        DROPPED = "dropped"  # never mined (see pipeline notes); manual review

    idempotency_key = models.CharField(max_length=128, unique=True)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="evm_transactions")
    network = models.ForeignKey(BlockchainNetwork, on_delete=models.PROTECT, related_name="evm_transactions")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="evm_transactions")
    from_address = models.CharField(max_length=42)
    to_address = models.CharField(max_length=42)
    # Amount in the asset's base units (integer, never a float).
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    is_token = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)
    nonce = models.BigIntegerField(null=True, blank=True)
    gas_limit = models.BigIntegerField(null=True, blank=True)
    max_fee_per_gas = models.DecimalField(max_digits=78, decimal_places=0, null=True, blank=True)
    max_priority_fee_per_gas = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True
    )
    sighash = models.CharField(max_length=66, blank=True)
    raw_transaction = models.TextField(blank=True)  # hex, once signed
    tx_hash = models.CharField(max_length=66, blank=True, db_index=True)
    block_number = models.BigIntegerField(null=True, blank=True)
    fee_wei = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True
    )  # gasUsed * effectiveGasPrice, captured at confirmation
    reservation = models.ForeignKey(
        BalanceReservation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evm_transactions",
    )
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="evm_tx_amount_positive"),
        ]

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"EvmTransaction({self.id}, {self.network.slug}, {self.status})"
