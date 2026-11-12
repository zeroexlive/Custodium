"""TON deposit scanning: per-account transaction polling.

TON has no block stream to walk — indexing follows account
histories by logical time, per the Phase 0 design (§§5–6):

- **Native TON** deposits are internal messages arriving at the
  wallet contract with value. Two look-alikes are explicitly NOT
  deposits and are filtered by body opcode: Jetton
  `transfer_notification`s (they carry a small forwarded TON
  amount) and `excesses` returns — plus anything sent by the
  wallet's own Jetton wallets, which is token machinery by
  definition.
- **Jetton** deposits are `internal_transfer` messages arriving
  at the wallet's Jetton wallet contract; the credited sender is
  the original owner recorded inside the payload. Bounced
  messages never credit: a bounce means the transfer failed.
- Crediting reuses the Phase 5 lifecycle; TON's registry policy
  is masterchain finality (0 extra confirmations), so the shared
  confirmation pass settles deposits once their masterchain
  reference exists. There is no reorg reversal on TON: shard
  blocks referenced by the masterchain are final.
"""

from __future__ import annotations

import base64
import binascii

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.indexing import services as indexing
from waas.modules.indexing.models import ObservedDeposit
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address

from . import addresses
from . import wallet as wallet_v4
from .cells import Cell, CellError
from .models import TonScanCursor
from .provider import TonProvider
from .service import resolve_jetton_account

_PAGE = 50


def _tx_hash_hex(tx: dict) -> str:
    raw = (tx.get("transaction_id") or {}).get("hash", "")
    try:
        return base64.b64decode(raw).hex()
    except (binascii.Error, ValueError):
        return str(raw).lower()


def _body_slice(tx: dict):
    body_b64 = (tx.get("in_msg") or {}).get("body")
    if not body_b64:
        return None
    try:
        return Cell.from_boc(base64.b64decode(body_b64)).begin_parse()
    except (CellError, binascii.Error, ValueError):
        return None


def _scan_account(
    *,
    network: BlockchainNetwork,
    account_raw: str,
    provider: TonProvider,
    handle_tx,
    master_seqno: int,
) -> int:
    """Poll one account's history; handle_tx(tx, in_msg, body) ->
    bool (deposit recorded). Returns deposits detected."""
    cursor, _ = TonScanCursor.objects.get_or_create(
        network=network, account_raw=account_raw
    )
    txs = provider.get_transactions(account_raw, limit=_PAGE)
    fresh = []
    for tx in txs:
        lt = int((tx.get("transaction_id") or {}).get("lt", 0))
        if lt > cursor.last_lt:
            fresh.append((lt, tx))
    fresh.sort(key=lambda item: item[0])
    detected = 0
    for lt, tx in fresh:
        in_msg = tx.get("in_msg") or {}
        if handle_tx(tx, in_msg, _body_slice(tx), master_seqno):
            detected += 1
        cursor.last_lt = lt
        cursor.last_tx_hash = _tx_hash_hex(tx)
        cursor.save(update_fields=["last_lt", "last_tx_hash", "updated_at"])
    return detected


@transaction.atomic
def scan_ton_once(
    *, network: BlockchainNetwork, provider: TonProvider
) -> indexing.ScanReport:
    """One TON indexing pass over every wallet of the network."""
    if provider.chain.network.id != network.id:
        raise ValueError("provider is configured for a different network")
    master_seqno = provider.get_masterchain_seqno()
    native_asset = Asset.objects.filter(network=network, token_standard="native").first()
    jetton_assets = list(
        Asset.objects.filter(network=network).exclude(token_standard="native")
    )
    detected = 0

    address_rows = list(
        Address.objects.filter(network=network).select_related("wallet")
    )
    jetton_by_wallet: dict[int, dict[str, Asset]] = {}
    for row in address_rows:
        owner_raw = row.normalized_address
        mapping: dict[str, Asset] = {}
        for asset in jetton_assets:
            account = resolve_jetton_account(
                wallet=row.wallet, asset=asset, owner_raw=owner_raw, provider=provider
            )
            mapping[account.jetton_wallet_raw] = asset
        jetton_by_wallet[row.wallet_id] = mapping

    for row in address_rows:
        wallet_raw = row.normalized_address
        own_jettons = set(jetton_by_wallet.get(row.wallet_id, {}))

        def handle_wallet_tx(tx, in_msg, body, seqno, *, row=row, own_jettons=own_jettons):
            if native_asset is None:
                return False
            if in_msg.get("bounced"):
                return False
            source = in_msg.get("source") or ""
            if not source:
                return False  # our own external-triggered sends
            try:
                source_raw = addresses.normalize(source)
            except ValueError:
                return False
            if source_raw in own_jettons:
                return False  # token machinery, never a TON deposit
            if body is not None and body.remaining_bits >= 32:
                op = body.read_uint(32)
                if op in (wallet_v4.JETTON_NOTIFICATION_OP, wallet_v4.EXCESSES_OP):
                    return False
            value = int(in_msg.get("value") or 0)
            if value <= 0:
                return False
            address_row = Address.objects.get(id=row.id)
            return indexing.record_deposit(
                network=network,
                address_row=address_row,
                asset=native_asset,
                tx_hash=_tx_hash_hex(tx),
                occurrence=0,
                from_address=source_raw,
                amount=value,
                block_number=seqno,
                block_hash=_tx_hash_hex(tx),
            )

        detected += _scan_account(
            network=network,
            account_raw=wallet_raw,
            provider=provider,
            handle_tx=handle_wallet_tx,
            master_seqno=master_seqno,
        )

        for jetton_raw, asset in jetton_by_wallet.get(row.wallet_id, {}).items():

            def handle_jetton_tx(tx, in_msg, body, seqno, *, row=row, asset=asset):
                if in_msg.get("bounced") or body is None:
                    return False
                if body.remaining_bits < 32 or body.read_uint(32) != wallet_v4.JETTON_INTERNAL_TRANSFER_OP:
                    return False
                body.read_uint(64)  # query_id
                amount = body.read_coins()
                sender_raw = body.read_address()
                if amount <= 0 or sender_raw is None:
                    return False
                address_row = Address.objects.get(id=row.id)
                return indexing.record_deposit(
                    network=network,
                    address_row=address_row,
                    asset=asset,
                    tx_hash=_tx_hash_hex(tx),
                    occurrence=0,
                    from_address=sender_raw,
                    amount=amount,
                    block_number=seqno,
                    block_hash=_tx_hash_hex(tx),
                )

            detected += _scan_account(
                network=network,
                account_raw=jetton_raw,
                provider=provider,
                handle_tx=handle_jetton_tx,
                master_seqno=master_seqno,
            )

    credited = indexing.run_confirmation_pass(network=network, head=master_seqno)
    return indexing.ScanReport(
        network=network.slug,
        head=master_seqno,
        scanned_from=None,
        scanned_to=None,
        deposits_detected=detected,
        deposits_credited=credited,
        reorg_depth=0,
        lag=0,
    )


# Referenced for parity with the other scanners' public surface.
__all__ = ["scan_ton_once", "ObservedDeposit"]
