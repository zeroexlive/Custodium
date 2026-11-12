from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Wallet(models.Model):
    """Tenant/project-scoped MPC wallet (docs/api/wallet-api.md §3).

    A wallet holds NO key material. ``*_key_ref`` fields are opaque
    identifiers issued by the MPC coordinator for a threshold key group;
    the shares themselves live only inside the MPC services (Phase 3).
    A wallet starts in ``provisioning`` and can only become ``active``
    when key generation has completed inside the MPC subsystem — the
    API offers no way to force activation.
    """

    class WalletType(models.TextChoices):
        MPC_THRESHOLD = "mpc_threshold", "MPC threshold wallet"

    class Status(models.TextChoices):
        PROVISIONING = "provisioning", "Provisioning (awaiting MPC key generation)"
        ACTIVE = "active", "Active"
        FROZEN = "frozen", "Frozen"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="wallets"
    )
    label = models.CharField(max_length=200)
    external_customer_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    wallet_type = models.CharField(
        max_length=24, choices=WalletType.choices, default=WalletType.MPC_THRESHOLD
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROVISIONING)
    # Opaque MPC coordinator references — never key material.
    ecdsa_key_ref = models.CharField(max_length=128, null=True, blank=True)
    ed25519_key_ref = models.CharField(max_length=128, null=True, blank=True)
    policy_name = models.CharField(max_length=100, blank=True, default="")
    policy_version = models.CharField(max_length=32, blank=True, default="")
    idempotency_key = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wallets_wallet"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="uniq_wallet_project_idempotency",
            )
        ]

    def __str__(self) -> str:
        return f"Wallet({self.id}, {self.label!r}, {self.status})"


class Address(models.Model):
    """A blockchain address recorded for a wallet (docs/api/wallet-api.md §4).

    Rows are created ONLY by the internal ``record_derived_address``
    service when the MPC/address-generation subsystem (Phases 3-4) has
    actually derived an address. The public API cannot create addresses
    yet, so no address in this table is ever fabricated.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="addresses")
    network = models.ForeignKey(
        "networks.BlockchainNetwork", on_delete=models.PROTECT, related_name="addresses"
    )
    address = models.CharField(max_length=128)
    normalized_address = models.CharField(max_length=128)
    derivation_path = models.CharField(max_length=64, blank=True, default="")
    derivation_index = models.BigIntegerField(null=True, blank=True)
    memo = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "wallets_address"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["network", "normalized_address"],
                name="uniq_address_network_normalized",
            )
        ]

    def __str__(self) -> str:
        return f"Address({self.network_id}, {self.address})"
