"""EVM chain scanner + deposit lifecycle (Phase 5).

One `scan_once` pass over a network:

1. **Reorg check first.** The cursor's last block hash is compared
   with the live chain; on mismatch the scanner walks back over its
   recorded block hashes, reversing every deposit in orphaned
   blocks (ledger reversals, never edits) until it finds the common
   ancestor, and resumes from there.
2. **Scan** new blocks: native transfers to watched addresses
   (receipt-verified) and ERC-20/BEP-20 `Transfer` logs to watched
   addresses become `ObservedDeposit` rows, each posting a
   DEPOSIT_OBSERVED journal entry (custody_pending /
   customer_pending). Replays are idempotent via the deposit
   uniqueness key + ledger idempotency keys.
3. **Confirmation pass.** Pending deposits whose block reaches the
   network's `confirmations_required` post one balanced
   DEPOSIT_CREDIT entry (pending → on-chain custody, pending →
   available). Deposits from manually blacklisted senders are held
   in pending for manual review and never auto-credited.

Watched addresses are the platform's recorded wallet addresses;
deposit credit scope matches the withdrawal reservation scope of
Phase 4 (`external_customer_id`, falling back to `wallet:<id>`).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.blacklist import services as blacklist_services
from waas.modules.evm import keys
from waas.modules.evm.provider import EvmProvider
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address

from .models import ChainCursor, ObservedDeposit, ScannedBlock

TRANSFER_TOPIC = "0x" + keys.keccak256(b"Transfer(address,address,uint256)").hex()
PRUNE_WINDOW = 512


@dataclass
class ScanReport:
    network: str
    head: int
    scanned_from: int | None
    scanned_to: int | None
    deposits_detected: int
    deposits_credited: int
    reorg_depth: int
    lag: int


def _scope_for_wallet(wallet) -> str:
    return wallet.external_customer_id or f"wallet:{wallet.id}"


def _account(project, asset, account_type, external_ref=""):
    return ledger_services.get_or_create_account(
        project=project, asset=asset, account_type=account_type, external_ref=external_ref
    )


def _post_observed(deposit: ObservedDeposit) -> None:
    wallet = deposit.wallet
    scope = _scope_for_wallet(wallet)
    entry, _ = ledger_services.post_journal(
        project=wallet.project,
        asset=deposit.asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_OBSERVED,
        lines=[
            {
                "account": _account(wallet.project, deposit.asset, AccountType.CUSTODY_PENDING),
                "side": "debit",
                "amount": int(deposit.amount),
            },
            {
                "account": _account(
                    wallet.project, deposit.asset, AccountType.CUSTOMER_PENDING, scope
                ),
                "side": "credit",
                "amount": int(deposit.amount),
            },
        ],
        idempotency_key=f"deposit:{deposit.id}:observed",
        operation_type="deposit",
        operation_id=str(deposit.id),
    )
    deposit.observed_entry = entry
    deposit.save(update_fields=["observed_entry", "updated_at"])


def _post_credit(deposit: ObservedDeposit) -> None:
    wallet = deposit.wallet
    scope = _scope_for_wallet(wallet)
    amount = int(deposit.amount)
    project, asset = wallet.project, deposit.asset
    entry, _ = ledger_services.post_journal(
        project=project,
        asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": _account(project, asset, AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": amount},
            {"account": _account(project, asset, AccountType.CUSTOMER_PENDING, scope),
             "side": "debit", "amount": amount},
            {"account": _account(project, asset, AccountType.CUSTODY_PENDING),
             "side": "credit", "amount": amount},
            {"account": _account(project, asset, AccountType.CUSTOMER_AVAILABLE, scope),
             "side": "credit", "amount": amount},
        ],
        idempotency_key=f"deposit:{deposit.id}:credit",
        operation_type="deposit",
        operation_id=str(deposit.id),
    )
    deposit.credit_entry = entry
    deposit.status = ObservedDeposit.Status.CREDITED
    deposit.save(update_fields=["credit_entry", "status", "updated_at"])
    from waas.modules.webhooks import services as webhook_services

    webhook_services.emit_event(
        project=project,
        event_type="deposit.credited",
        data={
            "deposit_id": str(deposit.id),
            "wallet_id": str(wallet.id),
            "network": deposit.network.slug,
            "asset": asset.symbol,
            "amount": str(amount),
            "tx_hash": deposit.tx_hash,
            "to_address": deposit.address,
        },
    )


def _reverse_deposit(deposit: ObservedDeposit) -> None:
    reason = f"chain reorganization removed block {deposit.block_number} ({deposit.block_hash})"
    if deposit.credit_entry_id is not None:
        ledger_services.reverse_entry(
            original=deposit.credit_entry,
            reason=reason,
            idempotency_key=f"deposit:{deposit.id}:reverse-credit",
        )
    if deposit.observed_entry_id is not None:
        ledger_services.reverse_entry(
            original=deposit.observed_entry,
            reason=reason,
            idempotency_key=f"deposit:{deposit.id}:reverse-observed",
        )
    deposit.status = ObservedDeposit.Status.REORGED_OUT
    deposit.save(update_fields=["status", "updated_at"])


def _record_deposit(
    *,
    network: BlockchainNetwork,
    address_row: Address,
    asset: Asset,
    tx_hash: str,
    occurrence: int,
    from_address: str,
    amount: int,
    block_number: int,
    block_hash: str,
) -> bool:
    """Create + observe a deposit unless this exact chain event was
    already recorded. Returns True when a new deposit was created."""
    # Hashes and addresses are stored EXACTLY as the family scanner
    # passes them: hex families canonicalise to lowercase, base58
    # families (Solana) are case-significant and must not be folded.
    deposit, created = ObservedDeposit.objects.get_or_create(
        network=network,
        tx_hash=tx_hash,
        occurrence=occurrence,
        block_hash=block_hash,
        defaults={
            "address": address_row,
            "wallet": address_row.wallet,
            "asset": asset,
            "from_address": from_address,
            "amount": amount,
            "block_number": block_number,
        },
    )
    if not created:
        return False
    wallet = address_row.wallet
    if blacklist_services.is_blacklisted(
        address=from_address, network=network, project=wallet.project
    ):
        deposit.held = True
        deposit.hold_reason = "sender is on the manual blacklist; held for manual review"
        deposit.save(update_fields=["held", "hold_reason", "updated_at"])
    _post_observed(deposit)
    return True


def _detect_in_block(
    *,
    network: BlockchainNetwork,
    block: dict,
    watched: dict[str, Address],
    native_asset: Asset | None,
    token_assets: dict[str, Asset],
    provider: EvmProvider,
) -> int:
    block_number = int(block["number"], 16)
    block_hash = str(block["hash"]).lower()
    detected = 0
    # Native transfers.
    if native_asset is not None:
        for index, tx in enumerate(block.get("transactions", [])):
            to = (tx.get("to") or "").lower()
            value = int(tx.get("value", "0x0"), 16)
            if to not in watched or value <= 0:
                continue
            receipt = provider.get_receipt(str(tx["hash"]))
            if receipt is None or int(receipt.get("status", "0x0"), 16) != 1:
                continue  # failed or unmined: not a deposit
            if _record_deposit(
                network=network,
                address_row=watched[to],
                asset=native_asset,
                tx_hash=str(tx["hash"]).lower(),
                occurrence=index,
                from_address=str(tx.get("from", "")).lower(),
                amount=value,
                block_number=block_number,
                block_hash=block_hash,
            ):
                detected += 1
    # Token transfers (Transfer logs to watched addresses).
    if token_assets:
        logs = provider.get_logs(
            addresses=list(token_assets),
            topics=[TRANSFER_TOPIC, None, None],
            from_block=block_number,
            to_block=block_number,
        )
        for log in logs:
            topics = log.get("topics", [])
            if len(topics) < 3:
                continue
            to = "0x" + topics[2][-40:].lower()
            if to not in watched:
                continue
            contract = str(log["address"]).lower()
            asset = token_assets.get(contract)
            if asset is None:
                continue
            amount = int(log.get("data", "0x0"), 16)
            if amount <= 0:
                continue
            if _record_deposit(
                network=network,
                address_row=watched[to],
                asset=asset,
                tx_hash=str(log["transactionHash"]).lower(),
                occurrence=int(log["logIndex"], 16),
                from_address="0x" + topics[1][-40:].lower(),
                amount=amount,
                block_number=block_number,
                block_hash=block_hash,
            ):
                detected += 1
    return detected


def _handle_reorg(network: BlockchainNetwork, provider: EvmProvider, cursor: ChainCursor) -> int:
    """Walk the cursor back to the common ancestor with the live
    chain, reversing deposits in orphaned blocks. Returns the
    number of blocks orphaned."""
    depth = 0
    while cursor.last_block_number >= 0:
        chain_hash = provider.get_block_hash(cursor.last_block_number)
        if chain_hash is not None and chain_hash.lower() == cursor.last_block_hash.lower():
            break
        orphaned = ObservedDeposit.objects.filter(
            network=network,
            block_number=cursor.last_block_number,
            block_hash=cursor.last_block_hash,
        ).exclude(status=ObservedDeposit.Status.REORGED_OUT)
        for deposit in orphaned:
            _reverse_deposit(deposit)
        ScannedBlock.objects.filter(
            network=network, number=cursor.last_block_number
        ).delete()
        depth += 1
        previous = (
            ScannedBlock.objects.filter(network=network)
            .order_by("-number")
            .first()
        )
        if previous is None:
            cursor.last_block_number = -1
            cursor.last_block_hash = ""
        else:
            cursor.last_block_number = previous.number
            cursor.last_block_hash = previous.hash
        cursor.save(update_fields=["last_block_number", "last_block_hash", "updated_at"])
    return depth


def _confirmation_pass(network: BlockchainNetwork, head: int) -> int:
    required = max(network.confirmations_required, 1)
    credited = 0
    pending = ObservedDeposit.objects.filter(
        network=network, status=ObservedDeposit.Status.PENDING, held=False
    )
    for deposit in pending:
        if head - deposit.block_number + 1 >= required:
            _post_credit(deposit)
            credited += 1
    return credited


@transaction.atomic
def scan_once(
    *, network: BlockchainNetwork, provider: EvmProvider, max_blocks: int = 64
) -> ScanReport:
    """One indexing pass for a network. See the module docstring."""
    if provider.chain.slug != network.slug:
        raise ValueError("provider is configured for a different network")
    provider.verify_chain()
    cursor, _ = ChainCursor.objects.get_or_create(network=network)
    reorg_depth = _handle_reorg(network, provider, cursor)
    head = provider.block_number()

    watched = {
        row.normalized_address: row
        for row in Address.objects.filter(network=network).select_related("wallet")
    }
    native_asset = Asset.objects.filter(network=network, token_standard="native").first()
    token_assets = {
        asset.contract_or_mint_address.lower(): asset
        for asset in Asset.objects.filter(network=network).exclude(
            contract_or_mint_address__isnull=True
        )
        if asset.contract_or_mint_address
    }

    scanned_from: int | None = None
    scanned_to: int | None = None
    detected = 0
    next_block = cursor.last_block_number + 1
    last = min(head, next_block + max_blocks - 1)
    for number in range(next_block, last + 1):
        block = provider.get_block(number)
        if block is None:
            break
        ScannedBlock.objects.update_or_create(
            network=network,
            number=number,
            defaults={
                "hash": str(block["hash"]).lower(),
                "parent_hash": str(block.get("parentHash", "")).lower(),
            },
        )
        detected += _detect_in_block(
            network=network,
            block=block,
            watched=watched,
            native_asset=native_asset,
            token_assets=token_assets,
            provider=provider,
        )
        cursor.last_block_number = number
        cursor.last_block_hash = str(block["hash"]).lower()
        cursor.save(update_fields=["last_block_number", "last_block_hash", "updated_at"])
        scanned_from = next_block if scanned_from is None else scanned_from
        scanned_to = number
    if cursor.last_block_number >= 0:
        ScannedBlock.objects.filter(
            network=network, number__lt=cursor.last_block_number - PRUNE_WINDOW
        ).delete()
    credited = _confirmation_pass(network, head)
    return ScanReport(
        network=network.slug,
        head=head,
        scanned_from=scanned_from,
        scanned_to=scanned_to,
        deposits_detected=detected,
        deposits_credited=credited,
        reorg_depth=reorg_depth,
        lag=max(head - cursor.last_block_number, 0),
    )


# -- shared lifecycle surface for other chain-family scanners ----
# (Phase 6 TRON reuses the deposit lifecycle; family scanners adapt
# their chain's blocks into these calls.)


def record_deposit(**kwargs) -> bool:
    """See `_record_deposit`."""
    return _record_deposit(**kwargs)


def reverse_deposit(deposit: ObservedDeposit) -> None:
    """See `_reverse_deposit`."""
    _reverse_deposit(deposit)


def run_confirmation_pass(*, network: BlockchainNetwork, head: int) -> int:
    """See `_confirmation_pass`."""
    return _confirmation_pass(network, head)


def reconciliation_report(*, network: BlockchainNetwork) -> dict:
    """Reconciliation for one network, per asset:

        expected custody = observed deposits (not reorged out)
                           − settled withdrawals
        ledger custody   = Σ balances of custody_onchain +
                           custody_pending accounts (project scope)

    The two must be equal when every chain event has been indexed
    exactly once and every settled withdrawal left custody through
    the pipeline. A nonzero difference is an operator alarm, not a
    rounding matter — all amounts are integers.
    """
    from django.db.models import Sum

    from waas.modules.evm.models import EvmTransaction
    from waas.modules.ledger.models import LedgerAccount
    from waas.modules.solana.models import SolanaTransaction
    from waas.modules.ton.models import TonTransaction
    from waas.modules.tron.models import TronTransaction

    deposit_totals = {
        row["asset"]: int(row["total"] or 0)
        for row in ObservedDeposit.objects.filter(network=network)
        .exclude(status=ObservedDeposit.Status.REORGED_OUT)
        .values("asset")
        .annotate(total=Sum("amount"))
    }
    withdrawal_totals: dict = {}
    for model in (EvmTransaction, TronTransaction, SolanaTransaction, TonTransaction):
        for row in (
            model.objects.filter(network=network, status=model.Status.CONFIRMED)
            .values("asset")
            .annotate(total=Sum("amount"))
        ):
            withdrawal_totals[row["asset"]] = withdrawal_totals.get(row["asset"], 0) + int(
                row["total"] or 0
            )
    rows = []
    for asset in Asset.objects.filter(network=network):
        ledger_custody = sum(
            ledger_services.account_balance(account)
            for account in LedgerAccount.objects.filter(
                asset=asset,
                account_type__in=[AccountType.CUSTODY_ONCHAIN, AccountType.CUSTODY_PENDING],
                external_ref="",
            )
        )
        deposits = deposit_totals.get(asset.id, 0)
        withdrawals = withdrawal_totals.get(asset.id, 0)
        expected = deposits - withdrawals
        rows.append(
            {
                "asset": asset.symbol,
                "contract_or_mint_address": asset.contract_or_mint_address,
                "observed_deposits": str(deposits),
                "settled_withdrawals": str(withdrawals),
                "expected_custody": str(expected),
                "ledger_custody": str(ledger_custody),
                "difference": str(ledger_custody - expected),
                "balanced": ledger_custody == expected,
            }
        )
    return {"network": network.slug, "assets": rows}
