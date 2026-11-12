"""TON withdrawal pipeline + wallet/jetton address management.

TON specifics on top of the platform pipeline semantics:

- **Seqno serialisation**: the wallet contract rejects any
  external message whose seqno is not exactly next. All sends
  from one wallet therefore run under the wallet row lock, and
  the seqno is always read from chain — never cached or guessed
  (Phase 0 design §3).
- **Signing**: the Ed25519 port signs the signing cell's *hash*
  (TON's convention), via the shared review-gated port.
- **Jetton sends** attach 0.05 TON to the internal message for
  the recipient-side gas/forwarding; the excess returns to the
  wallet. The attached amount is recorded, never hidden.
- A first send from an undeployed wallet carries its StateInit.
"""

from __future__ import annotations

import time

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.blacklist import services as blacklist_services
from waas.modules.ledger import services as ledger_services
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.solana.signing import Ed25519SignerPort, SigningUnavailable
from waas.modules.wallets.models import Address, Wallet
from waas.modules.wallets.services import record_derived_address

from . import addresses
from . import wallet as wallet_v4
from .models import TonJettonAccount, TonTransaction
from .provider import BroadcastRejected, ProviderUnavailable, TonError, TonProvider

TON_SLUGS = ("ton", "ton-testnet")
JETTON_ATTACH_NANO = 50_000_000  # 0.05 TON gas/forwarding attach


class TonServiceError(Exception):
    """A withdrawal was refused before any funds moved."""


def register_wallet_ton_addresses(
    *, wallet: Wallet, ed25519_public_key: bytes
) -> list[Address]:
    """Record the wallet's v4r2 contract address (friendly
    bounceable form, per the Phase 0 design's wallet policy) on
    every TON network."""
    raw = wallet_v4.wallet_address_raw(public_key=ed25519_public_key)
    created = []
    for network in BlockchainNetwork.objects.filter(slug__in=TON_SLUGS):
        friendly = addresses.raw_to_friendly(
            raw, bounceable=True, testnet=network.is_testnet
        )
        created.append(
            record_derived_address(wallet=wallet, network=network, address=friendly)
        )
    return created


def resolve_jetton_account(
    *, wallet: Wallet, asset: Asset, owner_raw: str, provider: TonProvider
) -> TonJettonAccount:
    """Get (or resolve + cache) the wallet's Jetton wallet
    contract address for a Jetton asset."""
    existing = TonJettonAccount.objects.filter(wallet=wallet, asset=asset).first()
    if existing is not None:
        return existing
    master_raw = addresses.normalize(asset.contract_or_mint_address or "")
    jetton_raw = provider.get_jetton_wallet_address(
        master_raw=master_raw, owner_raw=owner_raw
    )
    account, _ = TonJettonAccount.objects.get_or_create(
        wallet=wallet, asset=asset, defaults={"jetton_wallet_raw": jetton_raw}
    )
    return account


def _balance_scope(wallet: Wallet) -> str:
    return wallet.external_customer_id or f"wallet:{wallet.id}"


def _abort(tx: TonTransaction, reason: str) -> TonTransaction:
    if tx.reservation_id is not None:
        ledger_services.release_reservation(
            reservation=tx.reservation,
            idempotency_key=f"{tx.idempotency_key}:release",
        )
    tx.status = TonTransaction.Status.FAILED
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
    provider: TonProvider,
    actor_type: str = "api",
    actor_id: str = "",
) -> TonTransaction:
    existing = TonTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if provider.chain.network.id != network.id:
        raise TonServiceError("provider is configured for a different network")
    if asset.network_id != network.id:
        raise TonServiceError("asset does not belong to the network")
    if not addresses.is_valid(to_address, testnet=network.is_testnet):
        raise TonServiceError("destination is not a valid TON address for this network")
    to_raw = addresses.normalize(to_address)
    if amount <= 0:
        raise TonServiceError("amount must be positive")
    if blacklist_services.is_blacklisted(
        address=to_raw, network=network, project=wallet.project
    ):
        raise TonServiceError("destination address is blacklisted")
    address_row = Address.objects.filter(wallet=wallet, network=network).first()
    if address_row is None:
        raise TonServiceError("wallet has no recorded address on this network")
    from_raw = address_row.normalized_address

    # Serialise sends per wallet contract (seqno safety, design §3).
    Wallet.objects.select_for_update().get(id=wallet.id)

    is_jetton = asset.token_standard != "native"
    tx = TonTransaction.objects.create(
        idempotency_key=idempotency_key,
        wallet=wallet,
        network=network,
        asset=asset,
        from_raw=from_raw,
        to_address=to_address,
        to_raw=to_raw,
        amount=amount,
        is_jetton=is_jetton,
        attached_ton_nano=JETTON_ATTACH_NANO if is_jetton else 0,
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
        tx.status = TonTransaction.Status.FAILED
        tx.failure_reason = f"reservation failed: {exc}"[:500]
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    tx.reservation = reservation
    tx.status = TonTransaction.Status.RESERVED
    tx.save(update_fields=["reservation", "status", "updated_at"])

    try:
        seqno = provider.get_seqno(from_raw)
        state = provider.get_account_state(from_raw)
        if is_jetton:
            jetton = resolve_jetton_account(
                wallet=wallet, asset=asset, owner_raw=from_raw, provider=provider
            )
            body = wallet_v4.jetton_transfer_body(
                amount=amount,
                destination_raw=to_raw,
                response_raw=from_raw,
            )
            internal = wallet_v4.internal_message(
                destination_raw=jetton.jetton_wallet_raw,
                value_nano=JETTON_ATTACH_NANO,
                bounce=True,
                body=body,
            )
        else:
            internal = wallet_v4.internal_message(
                destination_raw=to_raw, value_nano=amount, bounce=True
            )
    except (TonError, ValueError) as exc:
        return _abort(tx, f"build failed: {exc}")

    try:
        public_key = signer.wallet_public_key(wallet)
    except SigningUnavailable as exc:
        return _abort(tx, f"signing unavailable: {exc}")
    # Sanity: the key the signer holds must be the key this
    # wallet's contract address was derived from.
    if wallet_v4.wallet_address_raw(public_key=public_key) != from_raw:
        return _abort(tx, "signer key does not match the wallet contract address")

    valid_until = int(time.time()) + 3600
    prepared = wallet_v4.prepare_transfer(
        public_key=public_key,
        seqno=seqno,
        internal=internal,
        valid_until=valid_until,
    )
    try:
        signature = signer.sign_message(wallet=wallet, message=prepared.signing_hash)
    except SigningUnavailable as exc:
        return _abort(tx, f"signing unavailable: {exc}")
    init = None
    if state != "active":
        init = wallet_v4.state_init_cell(
            code=wallet_v4.wallet_code_cell(),
            data=wallet_v4.wallet_data_cell(
                public_key=public_key,
                wallet_id=wallet_v4.wallet_id_for(0),
            ),
        )
    external = prepared.complete(signature, wallet_raw=from_raw, init=init)
    tx.seqno = seqno
    tx.valid_until = valid_until
    tx.external_message_hash = external.hash().hex()
    tx.status = TonTransaction.Status.SIGNED
    tx.save(
        update_fields=["seqno", "valid_until", "external_message_hash", "status", "updated_at"]
    )
    try:
        provider.send_boc_return_hash(external.to_boc())
    except BroadcastRejected as exc:
        return _abort(tx, f"broadcast rejected: {exc}")
    except ProviderUnavailable as exc:
        tx.status = TonTransaction.Status.DROPPED
        tx.failure_reason = f"broadcast outcome unknown: {exc}"[:500]
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        return tx
    tx.status = TonTransaction.Status.BROADCAST
    tx.save(update_fields=["status", "updated_at"])
    return tx


def confirm_transaction(*, tx: TonTransaction, provider: TonProvider) -> TonTransaction:
    """Find the wallet transaction that consumed our external
    message and settle/release from its execution result."""
    if tx.status in (
        TonTransaction.Status.CONFIRMED,
        TonTransaction.Status.REVERTED,
        TonTransaction.Status.FAILED,
    ):
        return tx
    if tx.status not in (TonTransaction.Status.BROADCAST, TonTransaction.Status.DROPPED):
        return tx
    if not tx.external_message_hash:
        return tx
    found = provider.find_transaction_by_message(tx.external_message_hash)
    if found is None:
        return tx  # not consumed yet (or never landed)
    tx.tx_hash = str(found.get("hash", "")).lower()
    fees = found.get("total_fees")
    tx.total_fees_nano = int(fees) if fees is not None else None
    tx.mc_block_seqno = found.get("mc_block_seqno")
    description = found.get("description") or {}
    compute = description.get("compute_ph") or {}
    action = description.get("action_ph") or {}
    bounced = bool(description.get("bounce_ph")) or bool(found.get("in_msg", {}).get("bounced"))
    success = bool(compute.get("success")) and bool(action.get("success", True))
    if not success or bounced:
        if tx.reservation_id is not None:
            ledger_services.release_reservation(
                reservation=tx.reservation,
                idempotency_key=f"{tx.idempotency_key}:release",
            )
        tx.status = TonTransaction.Status.REVERTED
        tx.failure_reason = (
            f"execution failed on-chain: compute={compute.get('exit_code')}, "
            f"action_success={action.get('success')}, bounced={bounced}"
        )[:500]
        tx.save(
            update_fields=[
                "tx_hash", "total_fees_nano", "mc_block_seqno",
                "status", "failure_reason", "updated_at",
            ]
        )
        return tx
    if tx.reservation_id is not None:
        ledger_services.settle_reservation(
            reservation=tx.reservation,
            idempotency_key=f"{tx.idempotency_key}:settle",
        )
    tx.status = TonTransaction.Status.CONFIRMED
    tx.save(
        update_fields=["tx_hash", "total_fees_nano", "mc_block_seqno", "status", "updated_at"]
    )
    return tx
