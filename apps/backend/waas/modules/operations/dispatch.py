"""Family dispatch: map a network to its chain module's
withdrawal pipeline (Phases 4–8).

Production signer factories return the fail-closed unavailable
signers — dispatch through the product in the platform's current
state therefore aborts honestly at the signing step (the Phase 3
review gate), after policy and reservations have done their work.
Tests inject working doubles through the same factories.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from waas.modules.evm import service as evm_service
from waas.modules.evm.chains import EVM_NETWORK_SLUGS
from waas.modules.evm.chains import resolve_chain as evm_chain
from waas.modules.evm.provider import EvmProvider
from waas.modules.evm.signing import UnavailableSigner
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.solana import service as solana_service
from waas.modules.solana.chains import SOLANA_NETWORK_SLUGS
from waas.modules.solana.chains import resolve_chain as solana_chain
from waas.modules.solana.provider import SolanaProvider
from waas.modules.solana.signing import UnavailableEd25519Signer
from waas.modules.ton import service as ton_service
from waas.modules.ton.chains import TON_NETWORK_SLUGS
from waas.modules.ton.chains import resolve_chain as ton_chain
from waas.modules.ton.provider import TonProvider
from waas.modules.tron import service as tron_service
from waas.modules.tron.chains import TRON_NETWORK_SLUGS
from waas.modules.tron.chains import resolve_chain as tron_chain
from waas.modules.tron.provider import TronProvider


def family_of(network: BlockchainNetwork) -> str:
    if network.slug in EVM_NETWORK_SLUGS:
        return "evm"
    if network.slug in TRON_NETWORK_SLUGS:
        return "tron"
    if network.slug in SOLANA_NETWORK_SLUGS:
        return "solana"
    if network.slug in TON_NETWORK_SLUGS:
        return "ton"
    raise ValueError(f"no chain family for network {network.slug}")


def default_provider(network: BlockchainNetwork):
    family = family_of(network)
    if family == "evm":
        return EvmProvider(evm_chain(network))
    if family == "tron":
        return TronProvider(tron_chain(network))
    if family == "solana":
        return SolanaProvider(solana_chain(network))
    return TonProvider(ton_chain(network))


def default_ecdsa_signer():
    # The MPC signer service is used only when the operator has
    # explicitly opened the gate (MPC_SIGNER_ENABLED + MPC_SIGNER_URL
    # in waas.modules.mpcsigner.client); otherwise fail closed.
    from waas.modules.mpcsigner.client import (
        RemoteEcdsaSigner,
        default_client,
        signer_enabled,
    )

    if signer_enabled():
        return RemoteEcdsaSigner(default_client())
    return UnavailableSigner()


def default_ed25519_signer():
    from waas.modules.mpcsigner.client import (
        RemoteEd25519Signer,
        default_client,
        signer_enabled,
    )

    if signer_enabled():
        return RemoteEd25519Signer(default_client())
    return UnavailableEd25519Signer()


@dataclass
class Factories:
    provider: Callable[[BlockchainNetwork], object] = default_provider
    ecdsa_signer: Callable[[], object] = default_ecdsa_signer
    ed25519_signer: Callable[[], object] = default_ed25519_signer


DEFAULT_FACTORIES = Factories()


def execute_transfer(
    *,
    wallet,
    network: BlockchainNetwork,
    asset,
    to_address: str,
    amount: int,
    idempotency_key: str,
    factories: Factories = DEFAULT_FACTORIES,
):
    """Run the family pipeline for one transfer; returns the
    chain transaction row. Shared by withdrawal dispatch
    (Phase 9) and sweeps (Phase 10) so both inherit identical
    chain safety (blacklist, signer gates, reservations)."""
    # Gas station preflight: a non-native transfer from a wallet
    # below the station threshold defers here (GasTopUpPending)
    # after broadcasting a native top-up from the funding wallet.
    from waas.modules.gasstation.services import preflight_transfer

    preflight_transfer(
        wallet=wallet,
        network=network,
        asset=asset,
        operation_key=idempotency_key,
        factories=factories,
    )
    family = family_of(network)
    provider = factories.provider(network)
    kwargs = {
        "wallet": wallet,
        "network": network,
        "asset": asset,
        "to_address": to_address,
        "amount": amount,
        "idempotency_key": idempotency_key,
        "provider": provider,
    }
    if family == "evm":
        return evm_service.execute_withdrawal(signer=factories.ecdsa_signer(), **kwargs)
    if family == "tron":
        return tron_service.execute_withdrawal(signer=factories.ecdsa_signer(), **kwargs)
    if family == "solana":
        return solana_service.execute_withdrawal(signer=factories.ed25519_signer(), **kwargs)
    return ton_service.execute_withdrawal(signer=factories.ed25519_signer(), **kwargs)


def execute(request, *, factories: Factories = DEFAULT_FACTORIES):
    """Run the family pipeline for an approved withdrawal
    request; returns the chain transaction row."""
    return execute_transfer(
        wallet=request.wallet,
        network=request.network,
        asset=request.asset,
        to_address=request.destination_address,
        amount=int(request.amount),
        idempotency_key=f"wd:{request.id}",
        factories=factories,
    )


def confirm(chain_tx, *, network: BlockchainNetwork, factories: Factories = DEFAULT_FACTORIES):
    """Advance a chain transaction toward settlement."""
    family = family_of(network)
    provider = factories.provider(network)
    if family == "evm":
        return evm_service.confirm_transaction(tx=chain_tx, provider=provider)
    if family == "tron":
        return tron_service.confirm_transaction(tx=chain_tx, provider=provider)
    if family == "solana":
        return solana_service.confirm_transaction(tx=chain_tx, provider=provider)
    return ton_service.confirm_transaction(tx=chain_tx, provider=provider)


def chain_tx_model(family: str):
    from waas.modules.evm.models import EvmTransaction
    from waas.modules.solana.models import SolanaTransaction
    from waas.modules.ton.models import TonTransaction
    from waas.modules.tron.models import TronTransaction

    return {
        "evm": EvmTransaction,
        "tron": TronTransaction,
        "solana": SolanaTransaction,
        "ton": TonTransaction,
    }[family]


def chain_tx_hash(chain_tx, family: str) -> str:
    if family == "evm":
        return chain_tx.tx_hash
    if family == "tron":
        return chain_tx.tx_id
    if family == "solana":
        return chain_tx.signature
    return chain_tx.tx_hash or chain_tx.external_message_hash


def chain_tx_fee(chain_tx, family: str) -> int | None:
    if family == "evm":
        return int(chain_tx.fee_wei) if chain_tx.fee_wei is not None else None
    if family == "tron":
        return chain_tx.fee_sun
    if family == "solana":
        return chain_tx.fee_lamports
    return chain_tx.total_fees_nano
