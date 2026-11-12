"""Solana chain registry: backend networks and their RPC endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from waas.modules.networks.models import BlockchainNetwork

SOLANA_NETWORK_SLUGS = frozenset({"solana", "solana-devnet"})

_DEFAULT_ENDPOINTS = {
    "solana": ("https://api.mainnet-beta.solana.com",),
    "solana-devnet": ("https://api.devnet.solana.com",),
}


@dataclass(frozen=True)
class SolanaChain:
    network: BlockchainNetwork
    endpoints: tuple[str, ...]


def resolve_chain(network: BlockchainNetwork) -> SolanaChain:
    if network.slug not in SOLANA_NETWORK_SLUGS:
        raise ValueError(f"not a Solana network: {network.slug}")
    configured: dict[str, list[str]] = getattr(settings, "SOLANA_RPC_ENDPOINTS", {}) or {}
    endpoints = tuple(configured.get(network.slug) or _DEFAULT_ENDPOINTS[network.slug])
    return SolanaChain(network=network, endpoints=endpoints)
