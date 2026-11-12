"""Solana withdrawal pipeline + wallet address registration.

Same safety semantics as the EVM/TRON pipelines (reserve → build →
sign → broadcast → confirm → settle; unknown broadcast outcome
holds the reservation). Solana specifics:

- Signing is Ed25519 over the *whole compiled message* via the
  Ed25519 signer port (Phase 3 FROST family, review-gated — the
  wired implementation fails closed).
- SOL moves with a SystemProgram transfer; SPL tokens move with
  TransferChecked between associated token accounts, preceded by
  an idempotent ATA creation for the destination so first-time
  recipients just work. Rent for the new ATA (~0.002 SOL) is paid
  by the sending wallet as fee payer — surfaced in the record's
  fee accounting at confirmation, never hidden.
"""

from __future__ import annotations

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.blacklist import services as blacklist_services
from waas.modules.ledger import services as ledger_services
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address, Wallet
from waas.modules.wallets.services import record_derived_address

from . import base58, keys
from . import transactions as sol_tx
from .models import SolanaTransaction
from .provider import ProviderUnavailable, SolanaProvider, TransactionRejected
from .signing import Ed25519SignerPort, SigningUnavailable

SOLANA_SLUGS = ("solana", "solana-devnet")


class SolanaServiceError(Exception):
    """A withdrawal was refused before any funds moved."""


def register_wallet_solana_addresses(
    *, wallet: Wallet, ed25519_public_key: bytes
) -> list[Address]:
    """Record the wallet's Solana address (base58 of its Ed25519
    group key) on every Solana network (idempotent)."""
    address = keys.address_from_public_key(ed25519_public_key)
    return [
        record_derived_address(wallet=wallet, network=network, address=address)
        for network in BlockchainNetwork.objects.filter(slug__in=SOLANA_SLUGS)
    ]


def _balance_scope(wallet: Wallet) -> str:
    return wallet.external_customer_id or f"wallet:{wallet.id}"


def _abort(tx: SolanaTransaction, reason: str) -> SolanaTransaction:
    if tx.reservation_id is not None:
        ledger_services.release_reservation(
            reservation=tx.reservation,
            idempotency_key=f"{tx.idempotency_key}:release",
        )
    tx.status = SolanaTransaction.Status.FAILED
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
    signer: Ed25519SignerPort,
    provider: SolanaProvider,
    actor_type: str = "api",
    actor_id: str = "",
) -> SolanaTransaction:
    existing = SolanaTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if provider.chain.network.id != network.id:
        raise SolanaServiceError("provider is configured for a different network")
    if asset.network_id != network.id:
        raise SolanaServiceError("asset does not belong to the network")
    if not keys.is_valid_address(to_address):
        raise SolanaServiceError("destination is not a valid Solana address")
    if amount <= 0:
        raise SolanaServiceError("amount must be positive")
    if blacklist_services.is_blacklisted(
        address=to_address, network=network, project=wallet.project
    ):
        raise SolanaServiceError("destination address is blacklisted")
    address_row = Address.objects.filter(wallet=wallet, network=network).first()
    if address_row is None:
        raise SolanaServiceError("wallet has no recorded address on this network")
    owner_address = address_row.address
    owner = keys.public_key_from_address(owner_address)
    destination = keys.public_key_from_address(to_address)

    tx = SolanaTransaction.objects.create(
        idempotency_key=idempotency_key,
        wallet=wallet,
        network=network,
        asset=asset,
        from_address=owner_address,
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
        tx.status = SolanaTransaction.Status.FAILED
        tx.failure_reason = f"reservation failed: {exc}"[:500]
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    tx.reservation = reservation
    tx.status = SolanaTransaction.Status.RESERVED
    tx.save(update_fields=["reservation", "status", "updated_at"])

    try:
        blockhash = provider.get_latest_blockhash()
        blockhash_bytes = base58.decode(blockhash)
        if tx.is_token:
            mint_address = asset.contract_or_mint_address or ""
            mint = keys.public_key_from_address(mint_address)
            source_ata = keys.public_key_from_address(
                keys.associated_token_address(owner=owner_address, mint=mint_address)
            )
            destination_ata_address = keys.associated_token_address(
                owner=to_address, mint=mint_address
            )
            destination_ata = keys.public_key_from_address(destination_ata_address)
            instructions = [
                sol_tx.create_associated_token_account_idempotent(
                    payer=owner, ata=destination_ata, owner=destination, mint=mint
                ),
                sol_tx.token_transfer_checked(
                    source_ata=source_ata,
                    mint=mint,
                    destination_ata=destination_ata,
                    owner=owner,
                    amount=amount,
                    decimals=asset.decimals,
                ),
            ]
        else:
            instructions = [
                sol_tx.system_transfer(
                    from_pubkey=owner, to_pubkey=destination, lamports=amount
                )
            ]
        compiled = sol_tx.compile_message(
            fee_payer=owner, instructions=instructions, recent_blockhash=blockhash_bytes
        )
    except (ProviderUnavailable, ValueError) as exc:
        return _abort(tx, f"build failed: {exc}")
    tx.recent_blockhash = blockhash
    tx.message_bytes = compiled.message_bytes.hex()
    tx.save(update_fields=["recent_blockhash", "message_bytes", "updated_at"])

    try:
        signature = signer.sign_message(wallet=wallet, message=compiled.message_bytes)
    except SigningUnavailable as exc:
        return _abort(tx, f"signing unavailable: {exc}")
    if len(signature) != 64:
        return _abort(tx, "signer returned a malformed Ed25519 signature")
    tx.signature = base58.encode(signature)
    tx.status = SolanaTransaction.Status.SIGNED
    tx.save(update_fields=["signature", "status", "updated_at"])

    wire = sol_tx.assemble_transaction(compiled.message_bytes, [signature])
    try:
        provider.send_transaction(wire)
    except TransactionRejected as exc:
        return _abort(tx, f"broadcast rejected: {exc}")
    except ProviderUnavailable as exc:
        tx.status = SolanaTransaction.Status.DROPPED
        tx.failure_reason = f"broadcast outcome unknown: {exc}"[:500]
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    tx.status = SolanaTransaction.Status.BROADCAST
    tx.save(update_fields=["status", "updated_at"])
    return tx


def confirm_transaction(
    *, tx: SolanaTransaction, provider: SolanaProvider
) -> SolanaTransaction:
    """Advance a broadcast transaction toward settlement."""
    if tx.status in (
        SolanaTransaction.Status.CONFIRMED,
        SolanaTransaction.Status.REVERTED,
        SolanaTransaction.Status.FAILED,
    ):
        return tx
    if tx.status not in (SolanaTransaction.Status.BROADCAST, SolanaTransaction.Status.DROPPED):
        return tx
    status = provider.get_signature_status(tx.signature)
    if status is None:
        return tx  # not landed yet (or, for dropped, never landed)
    slot_value = status.get("slot")
    tx.slot = int(slot_value) if slot_value is not None else None
    tx.save(update_fields=["slot", "updated_at"])
    if status.get("err") is not None:
        if tx.reservation_id is not None:
            ledger_services.release_reservation(
                reservation=tx.reservation,
                idempotency_key=f"{tx.idempotency_key}:release",
            )
        tx.status = SolanaTransaction.Status.REVERTED
        tx.failure_reason = f"transaction failed on-chain: {status.get('err')}"
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    head = provider.get_slot()
    required = max(tx.network.confirmations_required, 1)
    confirmations = 0 if tx.slot is None else head - tx.slot + 1
    if confirmations >= required or status.get("confirmationStatus") == "finalized":
        if tx.reservation_id is not None:
            ledger_services.settle_reservation(
                reservation=tx.reservation,
                idempotency_key=f"{tx.idempotency_key}:settle",
            )
        try:
            tx.fee_lamports = provider.get_transaction_fee(tx.signature)
        except Exception:
            tx.fee_lamports = None  # fee reporting must not block settlement
        tx.status = SolanaTransaction.Status.CONFIRMED
        tx.save(update_fields=["status", "fee_lamports", "updated_at"])
    return tx
