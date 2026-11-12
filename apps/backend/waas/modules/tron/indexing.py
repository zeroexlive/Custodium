"""TRON deposit scanning on the Phase 5 framework.

Same lifecycle, cursors, reorg walk-back and exactly-once rules as
the EVM scanner (`waas.modules.indexing`); this module only adapts
TRON block shapes into the shared `record_deposit` calls:

- Native TRX: `TransferContract` entries in successful block
  transactions (``ret.contractRet == "SUCCESS"``).
- TRC-20: `Transfer` logs from the transaction *info* of
  TriggerSmartContract transactions against known token contracts
  (logs live in tx info on TRON, not in the block). A failed
  receipt yields no deposit even if logs exist.

TRON's DPoS finality makes deep reorgs unlikely, but the walk-back
runs exactly as on EVM: orphaned blocks' deposits are reversed
through the ledger, never edited.
"""

from __future__ import annotations

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.indexing import services as indexing
from waas.modules.indexing.models import ChainCursor, ObservedDeposit, ScannedBlock
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address

from . import addresses
from .provider import TronProvider

_TRANSFER_TOPIC_HEX = indexing.TRANSFER_TOPIC[2:]  # without 0x
_PRUNE_WINDOW = 512


def _topic_address(topic_hex: str) -> str:
    return "41" + topic_hex[-40:].lower()


def _detect_in_block(
    *,
    network: BlockchainNetwork,
    block: dict,
    block_number: int,
    block_id: str,
    watched: dict[str, Address],
    native_asset: Asset | None,
    token_assets: dict[str, Asset],
    provider: TronProvider,
) -> int:
    detected = 0
    for index, tx in enumerate(block.get("transactions", [])):
        results = tx.get("ret") or []
        if not results or results[0].get("contractRet") != "SUCCESS":
            continue
        contracts = tx.get("raw_data", {}).get("contract", [])
        for contract in contracts:
            value = contract.get("parameter", {}).get("value", {})
            ctype = contract.get("type")
            if ctype == "TransferContract" and native_asset is not None:
                try:
                    to_hex = addresses.normalize_to_hex(str(value.get("to_address", "")))
                    from_hex = addresses.normalize_to_hex(str(value.get("owner_address", "")))
                except ValueError:
                    continue
                if to_hex not in watched:
                    continue
                if indexing.record_deposit(
                    network=network,
                    address_row=watched[to_hex],
                    asset=native_asset,
                    tx_hash=str(tx.get("txID", "")),
                    occurrence=index,
                    from_address=from_hex,
                    amount=int(value.get("amount", 0)),
                    block_number=block_number,
                    block_hash=block_id,
                ):
                    detected += 1
            elif ctype == "TriggerSmartContract":
                try:
                    contract_hex = addresses.normalize_to_hex(
                        str(value.get("contract_address", ""))
                    )
                except ValueError:
                    continue
                if contract_hex not in token_assets:
                    continue
                info = provider.get_transaction_info(str(tx.get("txID", "")))
                if info is None:
                    continue
                if str(info.get("receipt", {}).get("result", "")) not in ("", "SUCCESS"):
                    continue
                for log_pos, log in enumerate(info.get("log", [])):
                    topics = [str(t).lower() for t in log.get("topics", [])]
                    if len(topics) < 3 or topics[0] != _TRANSFER_TOPIC_HEX:
                        continue
                    to_hex = _topic_address(topics[2])
                    if to_hex not in watched:
                        continue
                    asset = token_assets.get("41" + str(log.get("address", "")).lower())
                    if asset is None:
                        continue
                    amount = int(str(log.get("data", "0")), 16)
                    if amount <= 0:
                        continue
                    if indexing.record_deposit(
                        network=network,
                        address_row=watched[to_hex],
                        asset=asset,
                        tx_hash=str(tx.get("txID", "")),
                        occurrence=log_pos,
                        from_address=_topic_address(topics[1]),
                        amount=amount,
                        block_number=block_number,
                        block_hash=block_id,
                    ):
                        detected += 1
    return detected


def _handle_reorg(network: BlockchainNetwork, provider: TronProvider, cursor: ChainCursor) -> int:
    depth = 0
    while cursor.last_block_number >= 0:
        chain_id = provider.get_block_id(cursor.last_block_number)
        if chain_id and chain_id.lower() == cursor.last_block_hash.lower():
            break
        orphaned = ObservedDeposit.objects.filter(
            network=network,
            block_number=cursor.last_block_number,
            block_hash=cursor.last_block_hash,
        ).exclude(status=ObservedDeposit.Status.REORGED_OUT)
        for deposit in orphaned:
            indexing.reverse_deposit(deposit)
        ScannedBlock.objects.filter(
            network=network, number=cursor.last_block_number
        ).delete()
        depth += 1
        previous = ScannedBlock.objects.filter(network=network).order_by("-number").first()
        if previous is None:
            cursor.last_block_number = -1
            cursor.last_block_hash = ""
        else:
            cursor.last_block_number = previous.number
            cursor.last_block_hash = previous.hash
        cursor.save(update_fields=["last_block_number", "last_block_hash", "updated_at"])
    return depth


@transaction.atomic
def scan_tron_once(
    *, network: BlockchainNetwork, provider: TronProvider, max_blocks: int = 64
) -> indexing.ScanReport:
    """One TRON indexing pass. See the module docstring."""
    if provider.chain.network.id != network.id:
        raise ValueError("provider is configured for a different network")
    cursor, _ = ChainCursor.objects.get_or_create(network=network)
    reorg_depth = _handle_reorg(network, provider, cursor)
    head = provider.head_number()

    watched = {
        row.normalized_address: row
        for row in Address.objects.filter(network=network).select_related("wallet")
    }
    native_asset = Asset.objects.filter(network=network, token_standard="native").first()
    token_assets: dict[str, Asset] = {}
    for asset in Asset.objects.filter(network=network).exclude(
        contract_or_mint_address__isnull=True
    ):
        if asset.contract_or_mint_address:
            try:
                token_assets[addresses.normalize_to_hex(asset.contract_or_mint_address)] = asset
            except ValueError:
                continue

    scanned_from: int | None = None
    scanned_to: int | None = None
    detected = 0
    next_block = cursor.last_block_number + 1
    last = min(head, next_block + max_blocks - 1)
    for number in range(next_block, last + 1):
        block = provider.get_block(number)
        if block is None:
            break
        block_id = str(block.get("blockID", "")).lower()
        header = block.get("block_header", {}).get("raw_data", {})
        ScannedBlock.objects.update_or_create(
            network=network,
            number=number,
            defaults={
                "hash": block_id,
                "parent_hash": str(header.get("parentHash", "")).lower(),
            },
        )
        detected += _detect_in_block(
            network=network,
            block=block,
            block_number=number,
            block_id=block_id,
            watched=watched,
            native_asset=native_asset,
            token_assets=token_assets,
            provider=provider,
        )
        cursor.last_block_number = number
        cursor.last_block_hash = block_id
        cursor.save(update_fields=["last_block_number", "last_block_hash", "updated_at"])
        scanned_from = next_block if scanned_from is None else scanned_from
        scanned_to = number
    if cursor.last_block_number >= 0:
        ScannedBlock.objects.filter(
            network=network, number__lt=cursor.last_block_number - _PRUNE_WINDOW
        ).delete()
    credited = indexing.run_confirmation_pass(network=network, head=head)
    return indexing.ScanReport(
        network=network.slug,
        head=head,
        scanned_from=scanned_from,
        scanned_to=scanned_to,
        deposits_detected=detected,
        deposits_credited=credited,
        reorg_depth=reorg_depth,
        lag=max(head - cursor.last_block_number, 0),
    )
