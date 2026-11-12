"""TRON chain registry: which backend networks are TRON, and how
to reach their nodes (TronGrid-style HTTP API)."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from waas.modules.networks.models import BlockchainNetwork

TRON_NETWORK_SLUGS = frozenset({"tron", "tron-nile"})

_DEFAULT_ENDPOINTS = {
    "tron": ("https://api.trongrid.io",),
    "tron-nile": ("https://nile.trongrid.io",),
}


@dataclass(frozen=True)
class TronChain:
    network: BlockchainNetwork
    endpoints: tuple[str, ...]


def resolve_chain(network: BlockchainNetwork) -> TronChain:
    if network.slug not in TRON_NETWORK_SLUGS:
        raise ValueError(f"not a TRON network: {network.slug}")
    configured: dict[str, list[str]] = getattr(settings, "TRON_API_ENDPOINTS", {}) or {}
    endpoints = tuple(configured.get(network.slug) or _DEFAULT_ENDPOINTS[network.slug])
    return TronChain(network=network, endpoints=endpoints)
