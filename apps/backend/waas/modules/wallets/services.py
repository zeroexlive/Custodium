"""Internal wallet services.

``record_derived_address`` is the ONLY way an Address row comes into
existence. It is called by MPC/address-generation integrations
(Phases 3-4) after real derivation — never by request handlers in
Phase 2, where derivation does not exist yet.
"""
from __future__ import annotations

from django.db import transaction

from waas.common.address_normalization import family_for_slug, normalize_address
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address, Wallet


@transaction.atomic
def record_derived_address(
    *,
    wallet: Wallet,
    network: BlockchainNetwork,
    address: str,
    derivation_path: str = "",
    derivation_index: int | None = None,
    memo: str = "",
) -> Address:
    family = family_for_slug(network.slug)
    normalized = normalize_address(family, address)
    existing = Address.objects.filter(
        network=network, normalized_address=normalized
    ).first()
    if existing is not None:
        if existing.wallet_id != wallet.id:
            raise ValueError("Address is already recorded for another wallet")
        return existing
    return Address.objects.create(
        wallet=wallet,
        network=network,
        address=address.strip(),
        normalized_address=normalized,
        derivation_path=derivation_path,
        derivation_index=derivation_index,
        memo=memo,
    )
