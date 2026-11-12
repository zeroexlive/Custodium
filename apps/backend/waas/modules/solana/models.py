"""The outbound Solana transaction record — one row per
withdrawal attempt, with the same state machine as the other
chains' pipelines. The transaction id is the base58 form of the
fee payer's Ed25519 signature."""

from __future__ import annotations

from django.db import models

from waas.modules.assets.models import Asset
from waas.modules.ledger.models import BalanceReservation
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Wallet


class SolanaTransaction(models.Model):
    class Status(models.TextChoices):
        CREATED = "created"
        RESERVED = "reserved"
        SIGNED = "signed"
        BROADCAST = "broadcast"
        CONFIRMED = "confirmed"
        REVERTED = "reverted"  # landed but the instruction failed (meta.err)
        FAILED = "failed"  # aborted locally; reservation released
        DROPPED = "dropped"  # broadcast outcome unknown; reservation HELD

    idempotency_key = models.CharField(max_length=200, unique=True)
    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="solana_transactions"
    )
    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.PROTECT, related_name="solana_transactions"
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="solana_transactions"
    )
    from_address = models.CharField(max_length=64)  # base58 wallet address
    to_address = models.CharField(max_length=64)  # base58, as supplied
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    is_token = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CREATED
    )
    signature = models.CharField(max_length=128, blank=True, db_index=True)
    recent_blockhash = models.CharField(max_length=64, blank=True)
    message_bytes = models.TextField(blank=True)  # hex of the compiled message
    slot = models.BigIntegerField(null=True, blank=True)
    fee_lamports = models.BigIntegerField(null=True, blank=True)
    reservation = models.ForeignKey(
        BalanceReservation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solana_transactions",
    )
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="solana_tx_amount_positive"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"SolanaTransaction({self.id}, {self.status}, sig={self.signature[:12]})"
