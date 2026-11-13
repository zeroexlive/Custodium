"""Signer-backed wallet provisioning.

This is the bridge the Phase 2 design promised: a wallet becomes
``active`` only when MPC key generation has actually completed.
Provisioning is an OPERATOR action (dashboard endpoint for
owner/administrator roles, or the ``provision_wallet`` management
command) and it only runs while the signer gate is open
(``MPC_SIGNER_ENABLED`` and ``MPC_SIGNER_URL`` — see
``waas.modules.mpcsigner``). With the gate closed, wallets remain
``provisioning``, exactly as before.

Flow (idempotent — safe to re-run after a partial failure):

1. Get-or-create the wallet's two threshold keys on the signer
   service (ECDSA + Ed25519 DKGs; shares never leave the signer
   nodes).
2. Derive one address per chain family from the GROUP public keys
   using each family's canonical derivation helper.
3. Record the address for every seeded network through
   ``record_derived_address`` (the only path that creates Address
   rows), store the opaque key ids on the wallet, flip the wallet
   to ``active`` and audit the event — the database writes happen
   in one transaction, AFTER the ceremonies have completed.

Custodium remains not Security Reviewed / not Production
Approved; opening the gate is an operator decision tracked by the
readiness checklist, and this module changes no defaults.
"""
from __future__ import annotations

from django.conf import settings
from django.db import transaction

from waas.common.address_normalization import family_for_slug
from waas.modules.audit.models import AuditEvent
from waas.modules.evm.keys import address_from_public_key as evm_address_from_public_key
from waas.modules.evm.signing import SigningUnavailable
from waas.modules.mpcsigner.client import (
    SignerServiceClient,
    default_client,
    key_id_for,
    signer_enabled,
)
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.solana.keys import (
    address_from_public_key as solana_address_from_public_key,
)
from waas.modules.ton.wallet import wallet_address_raw
from waas.modules.tron.addresses import (
    address_from_public_key as tron_address_from_public_key,
)
from waas.modules.wallets.models import Wallet
from waas.modules.wallets.services import record_derived_address


class ProvisioningUnavailable(Exception):
    """Provisioning cannot proceed; the wallet is left unchanged."""


def _get_or_create_key(
    client: SignerServiceClient, key_id: str, curve: str, threshold: int
) -> dict:
    """Fetch the key's public metadata, creating the key (a real
    DKG ceremony) when the signer service does not have it yet."""
    try:
        return client.get_key(key_id)
    except SigningUnavailable as exc:
        if "404" not in str(exc):
            raise ProvisioningUnavailable(str(exc)) from exc
    try:
        return client.create_key(key_id, curve, threshold)
    except SigningUnavailable as exc:
        if "409" in str(exc):  # created concurrently; fetch it
            try:
                return client.get_key(key_id)
            except SigningUnavailable as get_exc:
                raise ProvisioningUnavailable(str(get_exc)) from get_exc
        raise ProvisioningUnavailable(str(exc)) from exc


def derive_family_addresses(
    *, ecdsa_public_key: bytes, ed25519_public_key: bytes
) -> dict[str, str]:
    """One address per chain family, from the group public keys,
    via each family's canonical derivation (the same helpers the
    chain modules verify against)."""
    return {
        "evm": evm_address_from_public_key(ecdsa_public_key),
        "tron": tron_address_from_public_key(ecdsa_public_key),
        "solana": solana_address_from_public_key(ed25519_public_key),
        "ton": wallet_address_raw(public_key=ed25519_public_key),
    }


def provision_wallet(
    wallet: Wallet,
    *,
    actor_user=None,
    client: SignerServiceClient | None = None,
) -> Wallet:
    """Provision `wallet` end to end (see module docstring).

    Raises `ProvisioningUnavailable` — leaving the wallet untouched
    — when the gate is closed, the wallet's state forbids it, or
    the signer service fails.
    """
    network_count = BlockchainNetwork.objects.count()
    if network_count == 0:
        raise ProvisioningUnavailable(
            "the network registry is empty; run seed_networks_assets first"
        )
    if (
        wallet.status == Wallet.Status.ACTIVE
        and wallet.ecdsa_key_ref
        and wallet.ed25519_key_ref
        and wallet.addresses.count() >= network_count
    ):
        return wallet  # already fully provisioned; idempotent no-op
    if wallet.status not in (Wallet.Status.PROVISIONING, Wallet.Status.ACTIVE):
        raise ProvisioningUnavailable(
            f"a wallet in status '{wallet.status}' cannot be provisioned"
        )
    if not signer_enabled():
        raise ProvisioningUnavailable(
            "the MPC signer gate is closed (MPC_SIGNER_ENABLED and "
            "MPC_SIGNER_URL are not both set); the wallet remains provisioning"
        )
    client = client or default_client()
    threshold = int(getattr(settings, "MPC_SIGNER_THRESHOLD", 2))
    ecdsa_key_id = key_id_for(wallet, "ecdsa")
    ed25519_key_id = key_id_for(wallet, "ed25519")
    ecdsa_meta = _get_or_create_key(client, ecdsa_key_id, "secp256k1", threshold)
    ed25519_meta = _get_or_create_key(client, ed25519_key_id, "ed25519", threshold)
    if ecdsa_meta.get("curve") != "secp256k1" or ed25519_meta.get("curve") != "ed25519":
        raise ProvisioningUnavailable("signer service returned unexpected key metadata")
    addresses = derive_family_addresses(
        ecdsa_public_key=bytes.fromhex(ecdsa_meta["public_key"]),
        ed25519_public_key=bytes.fromhex(ed25519_meta["public_key"]),
    )
    ecdsa_public_hex = str(ecdsa_meta["public_key"]).lower()
    ed25519_public_hex = str(ed25519_meta["public_key"]).lower()
    with transaction.atomic():
        for network in BlockchainNetwork.objects.all().order_by("slug"):
            family = family_for_slug(network.slug)
            key_id = ecdsa_key_id if family in ("evm", "tron") else ed25519_key_id
            record_derived_address(
                wallet=wallet,
                network=network,
                address=addresses[family],
                derivation_path=f"signer-service:{key_id}",
            )
        wallet.ecdsa_key_ref = ecdsa_key_id
        wallet.ed25519_key_ref = ed25519_key_id
        wallet.ecdsa_public_key = ecdsa_public_hex
        wallet.ed25519_public_key = ed25519_public_hex
        wallet.status = Wallet.Status.ACTIVE
        wallet.save(
            update_fields=[
                "ecdsa_key_ref", "ed25519_key_ref",
                "ecdsa_public_key", "ed25519_public_key",
                "status", "updated_at",
            ]
        )
        AuditEvent.record(
            "wallet.provisioned",
            actor_user=actor_user,
            organization=wallet.project.organization,
            project=wallet.project,
            metadata={
                "wallet_id": str(wallet.id),
                "ecdsa_key_ref": ecdsa_key_id,
                "ed25519_key_ref": ed25519_key_id,
                "threshold": threshold,
                "networks": BlockchainNetwork.objects.count(),
            },
        )
    return wallet


def derive_address_for_network(wallet: Wallet, network) -> str:
    """Derive `wallet`'s address for one network from its stored
    group public keys — no signer call. Raises
    `ProvisioningUnavailable` when the wallet has not been
    provisioned (no public key recorded for the network's family).
    """
    family = family_for_slug(network.slug)
    if family in ("evm", "tron"):
        if not wallet.ecdsa_public_key:
            raise ProvisioningUnavailable(
                "wallet is not provisioned: no ECDSA group public key "
                "is recorded; provision the wallet before creating addresses"
            )
        public_key = bytes.fromhex(wallet.ecdsa_public_key)
        if family == "evm":
            return evm_address_from_public_key(public_key)
        return tron_address_from_public_key(public_key)
    if not wallet.ed25519_public_key:
        raise ProvisioningUnavailable(
            "wallet is not provisioned: no Ed25519 group public key "
            "is recorded; provision the wallet before creating addresses"
        )
    public_key = bytes.fromhex(wallet.ed25519_public_key)
    if family == "solana":
        return solana_address_from_public_key(public_key)
    return wallet_address_raw(public_key=public_key)
