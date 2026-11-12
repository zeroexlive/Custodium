"""On-chain native-balance reads per chain family.

Uses each family's existing provider surface (``get_balance`` on
EVM/Solana/TON; TRON derives the balance from its account read).
Returns ``None`` when the balance cannot be determined — the
caller treats unknown as "do not block the transfer" so the gas
station can never make money movement less reliable than it was
without one.
"""

from __future__ import annotations

from waas.modules.evm.chains import EVM_NETWORK_SLUGS
from waas.modules.solana.chains import SOLANA_NETWORK_SLUGS
from waas.modules.ton.chains import TON_NETWORK_SLUGS
from waas.modules.tron import addresses as tron_addresses
from waas.modules.tron.chains import TRON_NETWORK_SLUGS


def family_of_slug(slug: str) -> str | None:
    if slug in EVM_NETWORK_SLUGS:
        return "evm"
    if slug in TRON_NETWORK_SLUGS:
        return "tron"
    if slug in SOLANA_NETWORK_SLUGS:
        return "solana"
    if slug in TON_NETWORK_SLUGS:
        return "ton"
    return None


def native_balance(*, provider, network, address: str) -> int | None:
    family = family_of_slug(network.slug)
    try:
        if family == "evm":
            return int(provider.get_balance(address))
        if family == "solana":
            return int(provider.get_balance(address))
        if family == "ton":
            return int(provider.get_balance(address))
        if family == "tron":
            account = provider.get_account(tron_addresses.normalize_to_hex(address))
            if not account:
                return 0
            return int(account.get("balance") or 0)
    except Exception:
        return None
    return None
