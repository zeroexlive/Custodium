"""TRON withdrawal pipeline + wallet address registration.

The pipeline deliberately mirrors the Phase 4 EVM one — same
safety semantics, TRON mechanics:

    validate (asset/network, blacklist, recorded address)
      → reserve (ledger, idempotent)
      → build (ref block from the node's head; 1-hour expiry)
      → sign (signer port; fail-closed while review is pending)
      → broadcast (definite rejection aborts + releases; an
        UNKNOWN outcome marks the row dropped and HOLDS the
        reservation — never risk a double-pay)
      → confirm (receipt SUCCESS + confirmation threshold settles)

Signing digest = the txID (sha256 of the raw protobuf). The
signature is r ‖ s ‖ v with v the recovery id that reproduces the
wallet's own TRON address — found by trial recovery against the
group public key, never assumed.
"""

from __future__ import annotations

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.blacklist import services as blacklist_services
from waas.modules.evm import keys as evm_keys
from waas.modules.evm.signing import SignerPort, SigningUnavailable
from waas.modules.ledger import services as ledger_services
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address, Wallet
from waas.modules.wallets.services import record_derived_address

from . import addresses
from . import transactions as tron_tx
from .models import TronTransaction
from .provider import BroadcastRejected, ProviderUnavailable, TronProvider

TRON_SLUGS = ("tron", "tron-nile")


class TronServiceError(Exception):
    """A withdrawal was refused before any funds moved."""


def register_wallet_tron_addresses(*, wallet: Wallet, ecdsa_public_key: bytes) -> list[Address]:
    """Derive the wallet's TRON address from its ECDSA group key
    and record it on every TRON network (idempotent)."""
    address = addresses.address_from_public_key(ecdsa_public_key)
    recorded = []
    for network in BlockchainNetwork.objects.filter(slug__in=TRON_SLUGS):
        recorded.append(
            record_derived_address(wallet=wallet, network=network, address=address)
        )
    return recorded


def _balance_scope(wallet: Wallet) -> str:
    return wallet.external_customer_id or f"wallet:{wallet.id}"


def _find_signature(digest: bytes, r: int, s: int, owner_hex: str) -> bytes:
    """Assemble r‖s‖v choosing the recovery id whose recovered key
    owns `owner_hex` (the TRON signature's third component)."""
    for v in (0, 1):
        try:
            public = evm_keys.recover_public_key(digest, r, s, v)
        except ValueError:
            continue
        if addresses.hex_from_public_key(public) == owner_hex.lower():
            return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])
    raise TronServiceError("signer returned a signature that does not recover to the wallet address")


def _abort(tx: TronTransaction, reason: str) -> TronTransaction:
    if tx.reservation_id is not None:
        ledger_services.release_reservation(
            reservation=tx.reservation,
            idempotency_key=f"{tx.idempotency_key}:release",
        )
    tx.status = TronTransaction.Status.FAILED
    tx.failure_reason = reason[:500]
    tx.save(update_fields=["status", "failure_reason", "updated_at"])
    return tx


@transaction.atomic
def execute_withdrawal(
    *,
    wallet: Wallet,
    network: BlockchainNetwork,
    asset: Asset,
    to_address: str,
    amount: int,
    idempotency_key: str,
    signer: SignerPort,
    provider: TronProvider,
    actor_type: str = "api",
    actor_id: str = "",
) -> TronTransaction:
    """Run the withdrawal pipeline up to broadcast. Confirmation is
    a separate step (`confirm_transaction`) driven by the caller /
    indexer schedule."""
    existing = TronTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if provider.chain.network.id != network.id:
        raise TronServiceError("provider is configured for a different network")
    if asset.network_id != network.id:
        raise TronServiceError("asset does not belong to the network")
    try:
        to_hex = addresses.normalize_to_hex(to_address)
    except ValueError as exc:
        raise TronServiceError(f"destination is not a valid TRON address: {exc}") from exc
    if amount <= 0:
        raise TronServiceError("amount must be positive")
    if blacklist_services.is_blacklisted(
        address=to_hex, network=network, project=wallet.project
    ):
        raise TronServiceError("destination address is blacklisted")
    address_row = Address.objects.filter(wallet=wallet, network=network).first()
    if address_row is None:
        raise TronServiceError("wallet has no recorded address on this network")
    owner_hex = addresses.normalize_to_hex(address_row.address)

    tx = TronTransaction.objects.create(
        idempotency_key=idempotency_key,
        wallet=wallet,
        network=network,
        asset=asset,
        from_address=addresses.hex_to_base58(owner_hex),
        to_address=to_address,
        amount=amount,
        is_token=asset.token_standard != "native",
    )
    try:
        reservation, _ = ledger_services.reserve_funds(
            project=wallet.project,
            asset=asset,
            external_ref=_balance_scope(wallet),
            amount=amount,
            operation_type="withdrawal",
            operation_id=str(tx.id),
            idempotency_key=f"{idempotency_key}:reserve",
            actor_type=actor_type,
            actor_id=actor_id,
        )
    except Exception as exc:  # insufficient funds / ledger conflict
        tx.status = TronTransaction.Status.FAILED
        tx.failure_reason = f"reservation failed: {exc}"[:500]
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    tx.reservation = reservation
    tx.status = TronTransaction.Status.RESERVED
    tx.save(update_fields=["reservation", "status", "updated_at"])

    try:
        head = provider.now_block()
        if tx.is_token:
            contract_hex = addresses.normalize_to_hex(asset.contract_or_mint_address or "")
            built = tron_tx.build_token_transfer(
                owner_hex=owner_hex,
                contract_hex=contract_hex,
                to_hex=to_hex,
                amount=amount,
                ref_block_number=head["number"],
                ref_block_id=head["block_id"],
                timestamp_ms=head["timestamp_ms"],
            )
        else:
            built = tron_tx.build_native_transfer(
                owner_hex=owner_hex,
                to_hex=to_hex,
                amount_sun=amount,
                ref_block_number=head["number"],
                ref_block_id=head["block_id"],
                timestamp_ms=head["timestamp_ms"],
            )
    except (ProviderUnavailable, ValueError) as exc:
        return _abort(tx, f"build failed: {exc}")
    tx.contract_type = (
        "TransferContract" if not tx.is_token else "TriggerSmartContract"
    )
    tx.ref_block_num = built.ref_block_num
    tx.expiration_ms = built.expiration_ms
    tx.fee_limit_sun = built.fee_limit_sun
    tx.tx_id = built.tx_id()
    tx.raw_data_hex = built.raw_data_bytes().hex()
    tx.save(
        update_fields=[
            "contract_type", "ref_block_num", "expiration_ms", "fee_limit_sun",
            "tx_id", "raw_data_hex", "updated_at",
        ]
    )

    try:
        r, s = signer.sign_digest(wallet=wallet, digest=built.signing_digest())
        signature = _find_signature(built.signing_digest(), r, s, owner_hex)
    except SigningUnavailable as exc:
        return _abort(tx, f"signing unavailable: {exc}")
    except TronServiceError as exc:
        return _abort(tx, str(exc))
    tx.signature_hex = signature.hex()
    tx.status = TronTransaction.Status.SIGNED
    tx.save(update_fields=["signature_hex", "status", "updated_at"])

    try:
        provider.broadcast(built.broadcast_json(signature))
    except BroadcastRejected as exc:
        return _abort(tx, f"broadcast rejected: {exc}")
    except ProviderUnavailable as exc:
        # Unknown outcome: the transaction may be on its way to the
        # chain. Hold the reservation; the row is reconcilable by
        # tx_id (which is deterministic).
        tx.status = TronTransaction.Status.DROPPED
        tx.failure_reason = f"broadcast outcome unknown: {exc}"[:500]
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    tx.status = TronTransaction.Status.BROADCAST
    tx.save(update_fields=["status", "updated_at"])
    return tx


def confirm_transaction(
    *, tx: TronTransaction, provider: TronProvider
) -> TronTransaction:
    """Advance a broadcast transaction toward settlement."""
    if tx.status in (
        TronTransaction.Status.CONFIRMED,
        TronTransaction.Status.REVERTED,
        TronTransaction.Status.FAILED,
    ):
        return tx
    if tx.status not in (TronTransaction.Status.BROADCAST, TronTransaction.Status.DROPPED):
        return tx
    info = provider.get_transaction_info(tx.tx_id)
    if info is None:
        return tx  # not mined yet (or, for dropped, never landed)
    tx.block_number = int(info.get("blockNumber", 0)) or None
    if tx.block_number is None:
        tx.save(update_fields=["block_number", "updated_at"])
        return tx
    tx.save(update_fields=["block_number", "updated_at"])
    receipt = info.get("receipt", {})
    result = str(receipt.get("result", ""))
    tx.fee_sun = int(info.get("fee", 0))
    tx.save(update_fields=["fee_sun", "updated_at"])
    if info.get("result") == "FAILED" or (result and result != "SUCCESS"):
        if tx.reservation_id is not None:
            ledger_services.release_reservation(
                reservation=tx.reservation,
                idempotency_key=f"{tx.idempotency_key}:release",
            )
        tx.status = TronTransaction.Status.REVERTED
        tx.failure_reason = f"contract execution failed on-chain: {result or 'FAILED'}"
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    head = provider.head_number()
    required = max(tx.network.confirmations_required, 1)
    if head - tx.block_number + 1 >= required:
        if tx.reservation_id is not None:
            ledger_services.settle_reservation(
                reservation=tx.reservation,
                idempotency_key=f"{tx.idempotency_key}:settle",
            )
        tx.status = TronTransaction.Status.CONFIRMED
        tx.save(update_fields=["status", "updated_at"])
    return tx
