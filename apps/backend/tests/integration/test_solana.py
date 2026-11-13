"""Phase 7 Solana: withdrawal pipeline, deposit indexing
(balance-delta model), skipped slots, reorg — against an in-memory
RPC double. The signer is a TEST-ONLY single Ed25519 key;
production signing stays fail-closed behind the review gate.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.core.management import call_command

from waas.modules.assets.models import Asset
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.indexing.models import ObservedDeposit
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Organization
from waas.modules.projects.models import Project
from waas.modules.solana import base58, keys, service
from waas.modules.solana import indexing as sol_indexing
from waas.modules.solana.chains import SolanaChain
from waas.modules.solana.models import SolanaTransaction
from waas.modules.solana.provider import ProviderUnavailable, TransactionRejected
from waas.modules.solana.signing import UnavailableEd25519Signer
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db

TEST_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
TEST_PUBLIC = TEST_PRIVATE.public_key().public_bytes_raw()
OWNER = keys.address_from_public_key(TEST_PUBLIC)
SENDER = keys.address_from_public_key(bytes([8] * 32))
DEST = keys.address_from_public_key(bytes([9] * 32))
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"


class TestSigner:
    """TEST-ONLY signer double (single key). Never production."""

    def wallet_public_key(self, wallet) -> bytes:
        return TEST_PUBLIC

    def sign_message(self, wallet, message: bytes) -> bytes:
        return TEST_PRIVATE.sign(message)


class FakeSolanaProvider:
    def __init__(self, network, *, send_mode: str = "ok") -> None:
        self.chain = SolanaChain(network=network, endpoints=("memory://",))
        self.send_mode = send_mode
        self.slot = 0
        self.blocks: dict[int, dict] = {}
        self.statuses: dict[str, dict] = {}
        self.sent: list[bytes] = []
        self.salt = "a"

    def add_block(self, *, slot: int, txs=()) -> dict:
        block = {
            "blockhash": _fake_hash(self.salt, slot),
            "previousBlockhash": _fake_hash(self.salt, slot - 1),
            "transactions": list(txs),
        }
        self.blocks[slot] = block
        self.slot = max(self.slot, slot)
        return block

    def reorg(self, slot: int) -> None:
        self.salt = "b"
        if slot in self.blocks:
            self.blocks[slot] = {
                "blockhash": _fake_hash(self.salt, slot),
                "previousBlockhash": _fake_hash(self.salt, slot - 1),
                "transactions": [],
            }

    # provider surface ----------------------------------------------
    def get_slot(self) -> int:
        return self.slot

    def get_latest_blockhash(self) -> str:
        return _fake_hash(self.salt, self.slot)

    def get_balance(self, address: str) -> int:
        return 0

    def get_block(self, slot: int) -> dict | None:
        return self.blocks.get(slot)

    def get_signature_status(self, signature: str) -> dict | None:
        return self.statuses.get(signature)

    def send_transaction(self, transaction_bytes: bytes) -> str:
        if self.send_mode == "reject":
            raise TransactionRejected("Transaction simulation failed")
        if self.send_mode == "down":
            raise ProviderUnavailable("rpc unreachable")
        self.sent.append(transaction_bytes)
        return "sig"


def _fake_hash(salt: str, slot: int) -> str:
    import hashlib

    return base58.encode(hashlib.sha256(f"{salt}:{slot}".encode()).digest())


def sol_tx_json(*, signature: str, keys_in_order: list[str], pre: list[int], post: list[int],
                pre_token: list[dict] | None = None, post_token: list[dict] | None = None,
                err=None) -> dict:
    return {
        "transaction": {
            "signatures": [signature],
            "message": {"accountKeys": [{"pubkey": k} for k in keys_in_order]},
        },
        "meta": {
            "err": err,
            "preBalances": pre,
            "postBalances": post,
            "preTokenBalances": pre_token or [],
            "postTokenBalances": post_token or [],
        },
    }


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    user = get_user_model().objects.create_user(email="sol@example.com", password="x" * 12)
    org = Organization.objects.create(name="Sol Org", slug="sol-org")
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=user
    )
    solana = BlockchainNetwork.objects.get(slug="solana")
    solana.confirmations_required = 2
    solana.save(update_fields=["confirmations_required"])
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    service.register_wallet_solana_addresses(wallet=wallet, ed25519_public_key=TEST_PUBLIC)
    return {
        "project": project, "wallet": wallet, "solana": solana,
        "sol": Asset.objects.get(network=solana, symbol="SOL"),
        "usdt": Asset.objects.get(network=solana, symbol="USDT"),
        "user": user,
    }


def credit(ctx, asset, amount: int) -> None:
    ledger_services.post_journal(
        project=ctx["project"], asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": ledger_services.get_or_create_account(
                project=ctx["project"], asset=asset, account_type=AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": amount},
            {"account": ledger_services.get_or_create_account(
                project=ctx["project"], asset=asset,
                account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1"),
             "side": "credit", "amount": amount},
        ],
        idempotency_key=f"seed:{asset.id}", operation_type="deposit", operation_id="seed",
    )


def balance(ctx, asset, account_type, ref="cust_1") -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=asset, account_type=account_type, external_ref=ref
    )
    return ledger_services.account_balance(account)


def withdraw(ctx, provider, **overrides):
    params = {
        "wallet": ctx["wallet"], "network": ctx["solana"], "asset": ctx["sol"],
        "to_address": DEST, "amount": 400_000_000, "idempotency_key": "wd-sol-1",
        "signer": TestSigner(), "provider": provider,
    }
    params.update(overrides)
    return service.execute_withdrawal(**params)


# ---------------------------------------------------------- withdrawals


def test_sol_withdrawal_round_trip(ctx) -> None:
    credit(ctx, ctx["sol"], 1_000_000_000)
    provider = FakeSolanaProvider(ctx["solana"])
    tx = withdraw(ctx, provider)
    assert tx.status == SolanaTransaction.Status.BROADCAST
    # The wire transaction's signature verifies over the message
    # bytes with the wallet's Ed25519 key — what the chain checks.
    wire = provider.sent[0]
    signature, message = wire[1:65], wire[65:]
    TEST_PRIVATE.public_key().verify(signature, message)
    assert tx.signature == base58.encode(signature)

    provider.statuses[tx.signature] = {"slot": 0, "err": None, "confirmationStatus": "confirmed"}
    provider.slot = 1  # 2 slots of confirmation
    tx = service.confirm_transaction(tx=tx, provider=provider)
    assert tx.status == SolanaTransaction.Status.CONFIRMED
    assert balance(ctx, ctx["sol"], AccountType.CUSTOMER_AVAILABLE) == 600_000_000
    assert balance(ctx, ctx["sol"], AccountType.WITHDRAWAL_RESERVED) == 0
    assert ledger_services.trial_balance(ctx["project"], ctx["sol"]) == 0


def test_spl_withdrawal_builds_ata_and_transfer(ctx) -> None:
    credit(ctx, ctx["usdt"], 1_000_000)
    provider = FakeSolanaProvider(ctx["solana"])
    tx = withdraw(ctx, provider, asset=ctx["usdt"], amount=250_000, idempotency_key="wd-usdt-1")
    assert tx.status == SolanaTransaction.Status.BROADCAST
    message = bytes.fromhex(tx.message_bytes)
    # Two instructions: ATA create (program = ATA program) then
    # TransferChecked — both compiled into the message.
    assert keys.public_key_from_address(keys.ASSOCIATED_TOKEN_PROGRAM) in message
    assert bytes([12]) in message  # TransferChecked discriminator region
    dest_ata = keys.associated_token_address(owner=DEST, mint=USDT_MINT)
    assert base58.decode(dest_ata) in message


def test_signer_unavailable_aborts(ctx) -> None:
    credit(ctx, ctx["sol"], 1_000_000_000)
    provider = FakeSolanaProvider(ctx["solana"])
    tx = withdraw(ctx, provider, signer=UnavailableEd25519Signer())
    assert tx.status == SolanaTransaction.Status.FAILED
    assert provider.sent == []
    assert balance(ctx, ctx["sol"], AccountType.CUSTOMER_AVAILABLE) == 1_000_000_000


def test_broadcast_outcomes(ctx) -> None:
    credit(ctx, ctx["sol"], 2_000_000_000)
    rejected = withdraw(ctx, FakeSolanaProvider(ctx["solana"], send_mode="reject"))
    assert rejected.status == SolanaTransaction.Status.FAILED
    down = withdraw(
        ctx, FakeSolanaProvider(ctx["solana"], send_mode="down"),
        idempotency_key="wd-sol-2",
    )
    assert down.status == SolanaTransaction.Status.DROPPED
    assert balance(ctx, ctx["sol"], AccountType.WITHDRAWAL_RESERVED) == 400_000_000


def test_blacklisted_destination_refused(ctx) -> None:
    BlacklistEntry.objects.create(
        scope="platform", network=ctx["solana"], address=DEST,
        normalized_address=DEST, reason="test", created_by=ctx["user"],
    )
    provider = FakeSolanaProvider(ctx["solana"])
    with pytest.raises(service.SolanaServiceError):
        withdraw(ctx, provider)
    assert SolanaTransaction.objects.count() == 0


# ------------------------------------------------------------ deposits


def test_sol_deposit_via_balance_delta(ctx) -> None:
    provider = FakeSolanaProvider(ctx["solana"])
    tx = sol_tx_json(
        signature="sig-deposit-1",
        keys_in_order=[SENDER, OWNER],
        pre=[1_000_000_000, 100],
        post=[400_000_000, 600_000_100],
    )
    provider.add_block(slot=0, txs=[tx])
    provider.slot = 1
    report = sol_indexing.scan_solana_once(network=ctx["solana"], provider=provider)
    assert report.deposits_detected == 1
    deposit = ObservedDeposit.objects.get()
    assert int(deposit.amount) == 600_000_000  # delta, not the raw balance
    assert deposit.status == ObservedDeposit.Status.CREDITED
    assert balance(ctx, ctx["sol"], AccountType.CUSTOMER_AVAILABLE) == 600_000_000


def test_spl_deposit_attributed_by_owner(ctx) -> None:
    provider = FakeSolanaProvider(ctx["solana"])
    ata = keys.associated_token_address(owner=OWNER, mint=USDT_MINT)
    other_ata = keys.associated_token_address(owner=SENDER, mint=USDT_MINT)
    tx = sol_tx_json(
        signature="sig-deposit-2",
        keys_in_order=[SENDER],
        pre=[1_000_000_000],
        post=[999_995_000],
        pre_token=[
            {"accountIndex": 1, "mint": USDT_MINT, "owner": OWNER,
             "uiTokenAmount": {"amount": "100"}},
        ],
        post_token=[
            {"accountIndex": 1, "mint": USDT_MINT, "owner": OWNER,
             "uiTokenAmount": {"amount": "500100"}},
            {"accountIndex": 2, "mint": USDT_MINT, "owner": SENDER,
             "uiTokenAmount": {"amount": "999999"}},
        ],
    )
    # The token account addresses themselves are not watched; the
    # OWNER is — attribution must follow the owner (design §5.3).
    assert ata != other_ata
    provider.add_block(slot=0, txs=[tx])
    provider.slot = 1
    sol_indexing.scan_solana_once(network=ctx["solana"], provider=provider)
    deposit = ObservedDeposit.objects.get()
    assert deposit.asset == ctx["usdt"]
    assert int(deposit.amount) == 500_000
    assert balance(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE) == 500_000


def test_failed_tx_and_skipped_slots(ctx) -> None:
    provider = FakeSolanaProvider(ctx["solana"])
    failed = sol_tx_json(
        signature="sig-failed", keys_in_order=[SENDER, OWNER],
        pre=[1_000, 0], post=[0, 1_000], err={"InstructionError": [0, "Custom"]},
    )
    provider.add_block(slot=0, txs=[failed])
    # Slot 1 is skipped (no block); slot 2 is empty.
    provider.add_block(slot=2)
    provider.slot = 2
    sol_indexing.scan_solana_once(network=ctx["solana"], provider=provider)
    assert ObservedDeposit.objects.count() == 0
    from waas.modules.indexing.models import ChainCursor

    assert ChainCursor.objects.get(network=ctx["solana"]).last_block_number == 2


def test_solana_reorg_reverses_deposit(ctx) -> None:
    provider = FakeSolanaProvider(ctx["solana"])
    tx = sol_tx_json(
        signature="sig-deposit-3", keys_in_order=[SENDER, OWNER],
        pre=[1_000_000_000, 0], post=[500_000_000, 500_000_000],
    )
    provider.add_block(slot=0, txs=[tx])
    provider.slot = 1
    sol_indexing.scan_solana_once(network=ctx["solana"], provider=provider)
    assert balance(ctx, ctx["sol"], AccountType.CUSTOMER_AVAILABLE) == 500_000_000
    provider.reorg(0)
    sol_indexing.scan_solana_once(network=ctx["solana"], provider=provider)
    deposit = ObservedDeposit.objects.get()
    assert deposit.status == ObservedDeposit.Status.REORGED_OUT
    assert balance(ctx, ctx["sol"], AccountType.CUSTOMER_AVAILABLE) == 0
    assert ledger_services.trial_balance(ctx["project"], ctx["sol"]) == 0



# ---------------------------------------------------------- priority fees


class FeeProvider(FakeSolanaProvider):
    """Provider double that reports recent prioritization fees."""

    def __init__(self, network, fees):
        super().__init__(network)
        self._fees = fees

    def get_recent_prioritization_fees(self, addresses):
        return list(self._fees)


def test_priority_fee_instruction_prepended_at_median(ctx) -> None:
    import struct

    from waas.modules.solana import transactions as sol_tx

    credit(ctx, ctx["sol"], 1_000_000_000)
    provider = FeeProvider(ctx["solana"], [10_000, 30_000, 20_000])
    tx = withdraw(ctx, provider, idempotency_key="wd-prio-1")
    assert tx.status == "broadcast"
    message = bytes.fromhex(tx.message_bytes)
    # The ComputeBudget program is an account key in the message and
    # the SetComputeUnitPrice data (tag 3 + u64 LE median 20_000)
    # is present; with no fees reported, neither appears.
    assert sol_tx.COMPUTE_BUDGET_PROGRAM in message
    assert bytes([3]) + struct.pack("<Q", 20_000) in message

    provider2 = FeeProvider(ctx["solana"], [])
    tx2 = withdraw(ctx, provider2, idempotency_key="wd-prio-2")
    assert tx2.status == "broadcast"
    assert sol_tx.COMPUTE_BUDGET_PROGRAM not in bytes.fromhex(tx2.message_bytes)


def test_priority_fee_is_capped(ctx) -> None:
    import struct

    from waas.modules.solana import service as sol_service

    credit(ctx, ctx["sol"], 1_000_000_000)
    provider = FeeProvider(ctx["solana"], [10**9, 10**9])
    tx = withdraw(ctx, provider, idempotency_key="wd-prio-3")
    message = bytes.fromhex(tx.message_bytes)
    cap = sol_service.PRIORITY_FEE_CAP_MICRO_LAMPORTS
    assert bytes([3]) + struct.pack("<Q", cap) in message
