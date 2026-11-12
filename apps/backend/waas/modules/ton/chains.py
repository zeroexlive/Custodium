"""TON chain registry: backend networks and toncenter endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from waas.modules.networks.models import BlockchainNetwork

TON_NETWORK_SLUGS = frozenset({"ton", "ton-testnet"})

_DEFAULT_ENDPOINTS = {
    "ton": ("https://toncenter.com/api/v2",),
    "ton-testnet": ("https://testnet.toncenter.com/api/v2",),
}


@dataclass(frozen=True)
class TonChain:
    network: BlockchainNetwork
    endpoints: tuple[str, ...]  # toncenter v2 base URLs
    api_key: str = ""

    def v3_base(self, v2_base: str) -> str:
        return v2_base.rstrip("/").replace("/api/v2", "/api/v3")


def resolve_chain(network: BlockchainNetwork) -> TonChain:
    if network.slug not in TON_NETWORK_SLUGS:
        raise ValueError(f"not a TON network: {network.slug}")
    configured: dict[str, list[str]] = getattr(settings, "TON_API_ENDPOINTS", {}) or {}
    endpoints = tuple(configured.get(network.slug) or _DEFAULT_ENDPOINTS[network.slug])
    return TonChain(
        network=network,
        endpoints=endpoints,
        api_key=getattr(settings, "TON_API_KEY", "") or "",
    )
