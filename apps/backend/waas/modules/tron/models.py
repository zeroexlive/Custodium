"""The outbound TRON transaction record — one row per withdrawal
attempt, mirroring the EVM pipeline's state machine
(Phase 4 design) with TRON-native fields (txID, ref block,
fee limit in SUN instead of nonce/gas)."""

from __future__ import annotations

from django.db import models

from waas.modules.assets.models import Asset
from waas.modules.ledger.models import BalanceReservation
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Wallet


class TronTransaction(models.Model):
    class Status(models.TextChoices):
        CREATED = "created"
        RESERVED = "reserved"
        SIGNED = "signed"
        BROADCAST = "broadcast"
        CONFIRMED = "confirmed"
        REVERTED = "reverted"  # mined but contract execution failed
        FAILED = "failed"  # aborted locally; reservation released
        DROPPED = "dropped"  # broadcast outcome unknown; reservation HELD

    idempotency_key = models.CharField(max_length=200, unique=True)
    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="tron_transactions"
    )
    network = models.ForeignKey(
        BlockchainNetwork, on_delete=models.PROTECT, related_name="tron_transactions"
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, related_name="tron_transactions"
    )
    from_address = models.CharField(max_length=64)  # Base58Check form
    to_address = models.CharField(max_length=64)  # as supplied, validated
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    is_token = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CREATED
    )
    contract_type = models.CharField(max_length=32, blank=True)
    ref_block_num = models.BigIntegerField(null=True, blank=True)
    expiration_ms = models.BigIntegerField(null=True, blank=True)
    fee_limit_sun = models.BigIntegerField(default=0)
    tx_id = models.CharField(max_length=64, blank=True, db_index=True)
    raw_data_hex = models.TextField(blank=True)
    signature_hex = models.CharField(max_length=130, blank=True)
    block_number = models.BigIntegerField(null=True, blank=True)
    fee_sun = models.BigIntegerField(null=True, blank=True)
    reservation = models.ForeignKey(
        BalanceReservation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tron_transactions",
    )
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="tron_tx_amount_positive"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"TronTransaction({self.id}, {self.status}, tx={self.tx_id[:12]})"
