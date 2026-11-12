"""Gas station (post-roadmap module): automatic native-coin
top-ups so token transfers can pay their network fees.

A ``GasStation`` is configured per (project, network): a funding
wallet owned by the same project sends ``topup_amount`` of the
network's native asset to any project wallet whose on-chain
native balance falls below ``min_native_balance`` before a
non-native transfer is dispatched. The top-up is an ordinary
transfer through the shared chain pipelines (same signer gates,
reservations and confirmation tracking), journaled in the funding
wallet's own ledger scope — no special money path exists.
"""

from __future__ import annotations

import uuid

from django.db import models


class GasStation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="gas_stations"
    )
    network = models.ForeignKey(
        "networks.BlockchainNetwork", on_delete=models.PROTECT, related_name="gas_stations"
    )
    funding_wallet = models.ForeignKey(
        "wallets.Wallet", on_delete=models.PROTECT, related_name="funds_gas_stations"
    )
    enabled = models.BooleanField(default=True)
    # Native-asset base units. A wallet below min_native_balance is
    # topped up with topup_amount before a token transfer proceeds.
    min_native_balance = models.DecimalField(max_digits=78, decimal_places=0)
    topup_amount = models.DecimalField(max_digits=78, decimal_places=0)
    max_topups_per_day = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "network"], name="uniq_gas_station_project_network"
            )
        ]


class GasTopUp(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        BROADCAST = "broadcast", "Broadcast"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    station = models.ForeignKey(
        GasStation, on_delete=models.PROTECT, related_name="topups"
    )
    target_wallet = models.ForeignKey(
        "wallets.Wallet", on_delete=models.PROTECT, related_name="gas_topups"
    )
    network = models.ForeignKey(
        "networks.BlockchainNetwork", on_delete=models.PROTECT, related_name="gas_topups"
    )
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    # The idempotency key of the transfer that needed gas
    # (``wd:<id>`` / ``swp:<id>``): one live top-up per operation.
    operation_key = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    chain_tx_id = models.CharField(max_length=64, blank=True)
    chain_tx_hash = models.CharField(max_length=128, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
