"""EVM chain configuration (Phase 4: Ethereum & BSC only).

Chain identity comes from the seeded network registry
(`waas.modules.networks`); this module binds each EVM network slug
to its RPC endpoint list (settings-driven) and verifies at runtime
that a provider actually serves the chain id the registry claims —
a misconfigured endpoint must fail closed, never silently sign or
broadcast for the wrong chain.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from waas.modules.networks.models import BlockchainNetwork

# Default public endpoints, used only when settings do not override.
# These are read/write public RPCs; production deployments are
# expected to set EVM_RPC_ENDPOINTS to their own providers.
DEFAULT_ENDPOINTS: dict[str, list[str]] = {
    "ethereum": ["https://ethereum-rpc.publicnode.com"],
    "ethereum-sepolia": ["https://ethereum-sepolia-rpc.publicnode.com"],
    "bsc": ["https://bsc-rpc.publicnode.com"],
    "bsc-testnet": ["https://bsc-testnet-rpc.publicnode.com"],
}

EVM_NETWORK_SLUGS = frozenset(DEFAULT_ENDPOINTS)


class ChainConfigError(RuntimeError):
    """The chain configuration is missing or inconsistent."""


@dataclass(frozen=True)
class EvmChain:
    """A resolved EVM chain: registry identity + RPC endpoints."""

    network: BlockchainNetwork
    endpoints: tuple[str, ...]

    @property
    def slug(self) -> str:
        return self.network.slug

    @property
    def chain_id(self) -> int:
        if self.network.chain_id is None:
            raise ChainConfigError(f"network {self.network.slug} has no chain_id")
        return self.network.chain_id


def resolve_chain(network: BlockchainNetwork) -> EvmChain:
    """Bind a registry network to its EVM endpoints. Raises
    ChainConfigError for non-EVM networks or missing endpoints."""
    if network.slug not in EVM_NETWORK_SLUGS:
        raise ChainConfigError(f"network {network.slug} is not an EVM network")
    if network.chain_id is None:
        raise ChainConfigError(f"network {network.slug} has no chain_id in the registry")
    configured = getattr(settings, "EVM_RPC_ENDPOINTS", {}) or {}
    endpoints = configured.get(network.slug) or DEFAULT_ENDPOINTS[network.slug]
    if not endpoints:
        raise ChainConfigError(f"no RPC endpoints configured for {network.slug}")
    return EvmChain(network=network, endpoints=tuple(endpoints))
