from __future__ import annotations

import uuid

from django.db import models


class Asset(models.Model):
    """Chain-specific asset identity: network + contract/mint/master (+ program).

    An asset is NEVER identified by symbol alone. Native assets have a null
    contract address and token_standard='native'.
    """

    class IssuerClassification(models.TextChoices):
        NATIVE = "native", "Network native asset"
        ISSUER_NATIVE = "issuer_native", "Issuer-native (e.g. Tether USD₮)"
        BRIDGED_PEGGED = "bridged_pegged", "Bridged / pegged representation"
        THIRD_PARTY = "third_party", "Third-party token"
        UNKNOWN = "unknown", "Unknown — unverified"

    class VerificationStatus(models.TextChoices):
        VERIFIED = "verified", "Verified against issuer/explorer sources"
        UNVERIFIED = "unverified", "Unverified"
        REJECTED = "rejected", "Rejected"

    class OperationalStatus(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    network = models.ForeignKey(
        "networks.BlockchainNetwork", on_delete=models.CASCADE, related_name="assets"
    )
    symbol = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    decimals = models.PositiveSmallIntegerField()
    token_standard = models.CharField(max_length=32)  # native, ERC-20, BEP-20, TRC-20, SPL, Token-2022, Jetton
    contract_or_mint_address = models.CharField(max_length=128, null=True, blank=True)
    token_program = models.CharField(max_length=128, blank=True)  # e.g. Solana token program id
    issuer_classification = models.CharField(
        max_length=24, choices=IssuerClassification.choices, default=IssuerClassification.UNKNOWN
    )
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    risk_flags = models.JSONField(default=list, blank=True)
    deposit_enabled = models.BooleanField(default=False)
    withdrawal_enabled = models.BooleanField(default=False)
    operational_status = models.CharField(
        max_length=16, choices=OperationalStatus.choices, default=OperationalStatus.PLANNED
    )

    class Meta:
        db_table = "assets_asset"
        constraints = [
            models.UniqueConstraint(
                fields=["network", "token_standard", "contract_or_mint_address"],
                name="uniq_asset_network_standard_contract",
            )
        ]
        ordering = ["network__slug", "symbol"]

    def __str__(self) -> str:
        return f"{self.symbol} on {self.network.slug}"
