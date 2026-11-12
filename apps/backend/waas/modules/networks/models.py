from __future__ import annotations

import uuid

from django.db import models


class BlockchainNetwork(models.Model):
    class SignatureFamily(models.TextChoices):
        ECDSA_SECP256K1 = "ecdsa_secp256k1", "ECDSA secp256k1"
        ED25519 = "ed25519", "Ed25519"

    class OperationalStatus(models.TextChoices):
        PLANNED = "planned", "Planned"
        IN_DEVELOPMENT = "in_development", "In development"
        TESTNET = "testnet", "Testnet"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    chain_id = models.BigIntegerField(null=True, blank=True)  # EVM/TRON-style ids; null where N/A
    native_symbol = models.CharField(max_length=16)
    native_decimals = models.PositiveSmallIntegerField()
    signature_family = models.CharField(max_length=24, choices=SignatureFamily.choices)
    is_testnet = models.BooleanField(default=False)
    operational_status = models.CharField(
        max_length=24, choices=OperationalStatus.choices, default=OperationalStatus.PLANNED
    )
    confirmations_required = models.PositiveIntegerField(default=0)
    finality_description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "networks_blockchain_network"
        ordering = ["is_testnet", "slug"]

    def __str__(self) -> str:
        return self.slug
