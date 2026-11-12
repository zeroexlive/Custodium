"""Solana deposit scanning on the Phase 5 framework.

Detection follows the Phase 0 lookup design (§5.3): rather than
parsing instructions (transfers hide in inner instructions), the
scanner reads **balance deltas** from each transaction's meta:

- SOL: `postBalances − preBalances` for watched account keys.
- SPL: `postTokenBalances − preTokenBalances` entries whose
  **owner** is a watched wallet address, attributed to the asset
  by mint — the participant is the token account's *owner*, never
  the token account itself.

Failed transactions (`meta.err`) transfer nothing and are skipped.
The fee payer is recorded as the sender (exact for direct
transfers; the delta method's documented approximation for
program-mediated ones). Slots can be skipped on Solana: the
scanner advances over empty slots without treating them as
blocks, and its reorg walk-back anchors on real blocks only.
Finality: the registry's confirmation policy (32 slots) gates
crediting through the shared confirmation pass.
"""

from __future__ import annotations

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.indexing import services as indexing
from waas.modules.indexing.models import ChainCursor, ObservedDeposit, ScannedBlock
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address

from .provider import SolanaProvider

_PRUNE_WINDOW = 2048  # slots are ~0.4s; keep a wider window than EVM


def _detect_in_block(
    *,
    network: BlockchainNetwork,
    block: dict,
    slot: int,
    blockhash: str,
    watched: dict[str, Address],
    native_asset: Asset | None,
    token_assets: dict[str, Asset],
) -> int:
    detected = 0
    for tx in block.get("transactions", []):
        meta = tx.get("meta") or {}
        if meta.get("err") is not None:
            continue
        message = tx.get("transaction", {}).get("message", {})
        account_keys = [k.get("pubkey", "") for k in message.get("accountKeys", [])]
        signatures = tx.get("transaction", {}).get("signatures", [])
        if not signatures:
            continue
        tx_hash = signatures[0]
        fee_payer = account_keys[0] if account_keys else ""
        occurrence = 0

        def record(address_row, asset, amount, from_address, *, tx_hash=tx_hash):
            nonlocal detected, occurrence
            if indexing.record_deposit(
                network=network,
                address_row=address_row,
                asset=asset,
                tx_hash=tx_hash,
                occurrence=occurrence,
                from_address=from_address,
                amount=amount,
                block_number=slot,
                block_hash=blockhash,
            ):
                detected += 1
            occurrence += 1

        # Native SOL deltas.
        if native_asset is not None:
            pre = meta.get("preBalances", [])
            post = meta.get("postBalances", [])
            for i, key in enumerate(account_keys):
                if key in watched and i < len(pre) and i < len(post):
                    delta = int(post[i]) - int(pre[i])
                    if delta > 0:
                        record(watched[key], native_asset, delta, fee_payer)
        # SPL deltas by token-account owner.
        if token_assets:
            pre_map = {
                (b.get("accountIndex"), b.get("mint")): int(
                    b.get("uiTokenAmount", {}).get("amount", 0)
                )
                for b in meta.get("preTokenBalances", [])
            }
            for balance in meta.get("postTokenBalances", []):
                owner = balance.get("owner", "")
                mint = balance.get("mint", "")
                if owner not in watched or mint not in token_assets:
                    continue
                key = (balance.get("accountIndex"), mint)
                delta = int(balance.get("uiTokenAmount", {}).get("amount", 0)) - pre_map.get(key, 0)
                if delta > 0:
                    record(watched[owner], token_assets[mint], delta, fee_payer)
    return detected


def _handle_reorg(network: BlockchainNetwork, provider: SolanaProvider, cursor: ChainCursor) -> int:
    """Anchor on the newest recorded real block; orphan backwards
    while the live chain disagrees."""
    depth = 0
    while True:
        anchor = (
            ScannedBlock.objects.filter(
                network=network, number__lte=max(cursor.last_block_number, 0)
            )
            .order_by("-number")
            .first()
        )
        if anchor is None:
            return depth
        live = provider.get_block(anchor.number)
        live_hash = "" if live is None else str(live.get("blockhash", ""))
        if live_hash and live_hash == anchor.hash:
            return depth
        orphaned = ObservedDeposit.objects.filter(
            network=network, block_number=anchor.number, block_hash=anchor.hash
        ).exclude(status=ObservedDeposit.Status.REORGED_OUT)
        for deposit in orphaned:
            indexing.reverse_deposit(deposit)
        ScannedBlock.objects.filter(network=network, number=anchor.number).delete()
        depth += 1
        cursor.last_block_number = anchor.number - 1
        previous = (
            ScannedBlock.objects.filter(network=network).order_by("-number").first()
        )
        cursor.last_block_hash = previous.hash if previous else ""
        cursor.save(update_fields=["last_block_number", "last_block_hash", "updated_at"])


@transaction.atomic
def scan_solana_once(
    *, network: BlockchainNetwork, provider: SolanaProvider, max_blocks: int = 256
) -> indexing.ScanReport:
    """One Solana indexing pass (slots). See the module docstring."""
    if provider.chain.network.id != network.id:
        raise ValueError("provider is configured for a different network")
    cursor, _ = ChainCursor.objects.get_or_create(network=network)
    reorg_depth = _handle_reorg(network, provider, cursor)
    head = provider.get_slot()

    watched = {
        row.normalized_address: row
        for row in Address.objects.filter(network=network).select_related("wallet")
    }
    native_asset = Asset.objects.filter(network=network, token_standard="native").first()
    token_assets = {
        asset.contract_or_mint_address: asset
        for asset in Asset.objects.filter(network=network).exclude(
            contract_or_mint_address__isnull=True
        )
        if asset.contract_or_mint_address
    }

    scanned_from: int | None = None
    scanned_to: int | None = None
    detected = 0
    next_slot = cursor.last_block_number + 1
    last = min(head, next_slot + max_blocks - 1)
    for slot in range(next_slot, last + 1):
        block = provider.get_block(slot)
        if block is None:
            # Skipped slot: no block exists. Advance the cursor
            # without recording a block.
            cursor.last_block_number = slot
            cursor.save(update_fields=["last_block_number", "updated_at"])
            continue
        blockhash = str(block.get("blockhash", ""))
        ScannedBlock.objects.update_or_create(
            network=network,
            number=slot,
            defaults={
                "hash": blockhash,
                "parent_hash": str(block.get("previousBlockhash", "")),
            },
        )
        detected += _detect_in_block(
            network=network,
            block=block,
            slot=slot,
            blockhash=blockhash,
            watched=watched,
            native_asset=native_asset,
            token_assets=token_assets,
        )
        cursor.last_block_number = slot
        cursor.last_block_hash = blockhash
        cursor.save(update_fields=["last_block_number", "last_block_hash", "updated_at"])
        scanned_from = next_slot if scanned_from is None else scanned_from
        scanned_to = slot
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
