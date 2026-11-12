"""EVM service layer (Phase 4): address registration for MPC
wallets and the withdrawal pipeline.

Address integration: when the MPC subsystem produces a wallet's
secp256k1 group public key (Phase 3), the EVM address is a pure
derivation of it — the same address on every EVM chain. This module
records those derived addresses through the wallets module's
internal `record_derived_address` service (the only legitimate way
Address rows come to exist). It does NOT activate wallets:
activation remains gated on MPC key generation completing under the
Phase 3 review rules.

Withdrawal pipeline: reserve → build → sign → broadcast → confirm →
settle, idempotent at every step via the transaction's idempotency
key and the ledger's own idempotency keys. In production this maps
one-to-one onto a Temporal workflow (ADR 0003); here it is a
synchronous service with a per-wallet row lock serialising nonce
allocation. Signing goes through `SignerPort` — with the only
currently wired implementation (`UnavailableSigner`) every real
attempt aborts cleanly at the signing step with the reservation
released, which is the correct behaviour until the MPC review gate
opens.
"""

from __future__ import annotations

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.blacklist import services as blacklist_services
from waas.modules.ledger import services as ledger_services
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address, Wallet
from waas.modules.wallets.services import record_derived_address

from . import keys, transactions
from .chains import EVM_NETWORK_SLUGS, resolve_chain
from .models import EvmTransaction
from .provider import EvmProvider, ProviderError, ProviderUnavailable, RevertError
from .signing import SignerPort, SigningUnavailable


class EvmServiceError(RuntimeError):
    """A pipeline precondition failed (bad asset/network pairing,
    missing address, blacklisted destination, ...)."""


def register_wallet_evm_addresses(
    *, wallet: Wallet, ecdsa_public_key: bytes
) -> list[Address]:
    """Derive the wallet's EVM address from its MPC group public key
    and record it for every EVM network. Idempotent: re-registering
    returns the existing rows."""
    address = keys.address_from_public_key(ecdsa_public_key)
    recorded: list[Address] = []
    for network in BlockchainNetwork.objects.filter(slug__in=EVM_NETWORK_SLUGS).order_by("slug"):
        recorded.append(
            record_derived_address(
                wallet=wallet,
                network=network,
                address=address,
                derivation_path="evm",
            )
        )
    return recorded


def _fail(tx: EvmTransaction, reason: str, *, release: bool) -> EvmTransaction:
    tx.status = EvmTransaction.Status.FAILED
    tx.failure_reason = reason
    tx.save(update_fields=["status", "failure_reason", "updated_at"])
    if release and tx.reservation is not None:
        ledger_services.release_reservation(
            reservation=tx.reservation,
            idempotency_key=f"{tx.idempotency_key}:release",
        )
    return tx


def execute_withdrawal(
    *,
    wallet: Wallet,
    network: BlockchainNetwork,
    asset: Asset,
    to_address: str,
    amount: int,
    idempotency_key: str,
    signer: SignerPort,
    provider: EvmProvider,
) -> EvmTransaction:
    """Run the withdrawal pipeline up to broadcast. Confirmation is
    a separate step (`confirm_transaction`) so callers can poll.

    Re-entering with an existing idempotency key returns the stored
    transaction without repeating any side effect.
    """
    existing = EvmTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing

    chain = resolve_chain(network)
    if provider.chain.slug != chain.slug:
        raise EvmServiceError("provider is configured for a different chain")
    provider.verify_chain()

    if asset.network_id != network.id:
        raise EvmServiceError("asset does not belong to the given network")
    is_token = asset.token_standard != "native"
    if is_token and not asset.contract_or_mint_address:
        raise EvmServiceError("token asset has no contract address")
    if amount <= 0:
        raise EvmServiceError("amount must be positive")
    destination = keys.normalize_address(to_address)
    if blacklist_services.is_blacklisted(
        address=destination, network=network, project=wallet.project
    ):
        raise EvmServiceError("destination address is on the manual blacklist")

    address_row = (
        Address.objects.filter(wallet=wallet, network=network).order_by("id").first()
    )
    if address_row is None:
        raise EvmServiceError(
            "wallet has no recorded address on this network "
            "(register the MPC public key first)"
        )
    from_address = keys.normalize_address(address_row.address)

    with transaction.atomic():
        # Serialise nonce allocation per wallet for this synchronous
        # pipeline (production: Temporal + a dedicated allocator).
        Wallet.objects.select_for_update().get(pk=wallet.pk)
        tx = EvmTransaction.objects.create(
            idempotency_key=idempotency_key,
            wallet=wallet,
            network=network,
            asset=asset,
            from_address=from_address,
            to_address=destination,
            amount=amount,
            is_token=is_token,
        )
        # The reservation draws on the wallet's customer-scope
        # available account (deposits for this wallet's customer
        # must be credited to the same scope — see Phase 5).
        balance_scope = wallet.external_customer_id or f"wallet:{wallet.id}"
        try:
            reservation, _created = ledger_services.reserve_funds(
                project=wallet.project,
                asset=asset,
                external_ref=balance_scope,
                amount=amount,
                operation_type="withdrawal",
                operation_id=str(tx.id),
                idempotency_key=f"{idempotency_key}:reserve",
            )
        except Exception as exc:  # insufficient funds / ledger conflict
            tx.status = EvmTransaction.Status.FAILED
            tx.failure_reason = f"reservation failed: {exc}"
            tx.save(update_fields=["status", "failure_reason", "updated_at"])
            return tx
        tx.reservation = reservation
        tx.status = EvmTransaction.Status.RESERVED
        tx.save(update_fields=["reservation", "status", "updated_at"])

        # -- build ------------------------------------------------
        try:
            nonce = provider.get_transaction_count(from_address)
            max_fee, priority = provider.fee_data()
            if is_token:
                data = transactions.erc20_transfer_data(destination, amount)
                gas_limit = provider.estimate_gas(
                    from_address=from_address,
                    to=asset.contract_or_mint_address,
                    value=0,
                    data=data,
                )
                unsigned = transactions.build_token_transfer(
                    chain_id=chain.chain_id,
                    nonce=nonce,
                    token_contract=asset.contract_or_mint_address,
                    to=destination,
                    amount=amount,
                    gas_limit=gas_limit,
                    max_fee_per_gas=max_fee,
                    max_priority_fee_per_gas=priority,
                )
            else:
                gas_limit = 21_000
                unsigned = transactions.build_native_transfer(
                    chain_id=chain.chain_id,
                    nonce=nonce,
                    to=destination,
                    amount_wei=amount,
                    gas_limit=gas_limit,
                    max_fee_per_gas=max_fee,
                    max_priority_fee_per_gas=priority,
                )
        except RevertError as exc:
            return _fail(tx, f"transaction would revert: {exc}", release=True)
        except ProviderError as exc:
            return _fail(tx, f"provider error while building: {exc}", release=True)

        sighash = unsigned.sighash()
        tx.nonce = nonce
        tx.gas_limit = gas_limit
        tx.max_fee_per_gas = max_fee
        tx.max_priority_fee_per_gas = priority
        tx.sighash = "0x" + sighash.hex()
        tx.save(
            update_fields=[
                "nonce", "gas_limit", "max_fee_per_gas",
                "max_priority_fee_per_gas", "sighash", "updated_at",
            ]
        )

        # -- sign ---------------------------------------------------
        try:
            public_key = signer.wallet_public_key(wallet)
            r, s = signer.sign_digest(wallet, sighash)
        except SigningUnavailable as exc:
            return _fail(tx, f"signing unavailable: {exc}", release=True)
        recovery_id = keys.find_recovery_id(sighash, r, s, public_key)
        raw = unsigned.assemble_signed(r, s, recovery_id)
        tx.raw_transaction = "0x" + raw.hex()
        tx.tx_hash = "0x" + transactions.transaction_hash(raw).hex()
        tx.status = EvmTransaction.Status.SIGNED
        tx.save(update_fields=["raw_transaction", "tx_hash", "status", "updated_at"])

        # -- broadcast ----------------------------------------------
        try:
            tx.tx_hash = provider.send_raw_transaction(raw)
        except ProviderUnavailable as exc:
            # The transaction may or may not be on the network. Do
            # NOT release the reservation; a human (or a later,
            # smarter reconciler) must resolve this by tx hash.
            tx.status = EvmTransaction.Status.DROPPED
            tx.failure_reason = (
                f"broadcast outcome unknown: {exc}. "
                f"Verify tx {tx.tx_hash} before taking any further action."
            )
            tx.save(update_fields=["status", "failure_reason", "tx_hash", "updated_at"])
            return tx
        except ProviderError as exc:
            return _fail(tx, f"broadcast rejected: {exc}", release=True)
        tx.status = EvmTransaction.Status.BROADCAST
        tx.save(update_fields=["status", "tx_hash", "updated_at"])
        return tx


def confirm_transaction(
    *, tx: EvmTransaction, provider: EvmProvider
) -> EvmTransaction:
    """Advance a broadcast transaction toward settlement. Safe to
    call repeatedly: returns the row unchanged while the receipt is
    missing or confirmations are insufficient; settles the ledger
    reservation exactly once when the chain's confirmation target
    is met; releases it if the transaction reverted on-chain."""
    if tx.status != EvmTransaction.Status.BROADCAST:
        return tx
    receipt = provider.get_receipt(tx.tx_hash)
    if receipt is None:
        return tx
    if int(receipt.get("status", "0x0"), 16) == 0:
        tx.status = EvmTransaction.Status.REVERTED
        tx.block_number = int(receipt["blockNumber"], 16)
        tx.failure_reason = "transaction reverted on-chain"
        tx.save(update_fields=["status", "block_number", "failure_reason", "updated_at"])
        if tx.reservation is not None:
            ledger_services.release_reservation(
                reservation=tx.reservation,
                idempotency_key=f"{tx.idempotency_key}:release",
            )
        return tx
    tx.block_number = int(receipt["blockNumber"], 16)
    confirmations = provider.block_number() - tx.block_number + 1
    required = max(tx.network.confirmations_required, 1)
    if confirmations < required:
        tx.save(update_fields=["block_number", "updated_at"])
        return tx
    if tx.reservation is not None:
        ledger_services.settle_reservation(
            reservation=tx.reservation,
            idempotency_key=f"{tx.idempotency_key}:settle",
        )
    tx.status = EvmTransaction.Status.CONFIRMED
    tx.save(update_fields=["status", "block_number", "updated_at"])
    return tx
