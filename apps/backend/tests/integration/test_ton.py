"""Phase 8 TON: wallet-v4 withdrawal pipeline and per-account
deposit scanning against an in-memory toncenter double. The
signer is a TEST-ONLY single Ed25519 key; production signing
stays fail-closed behind the review gate.
"""

from __future__ import annotations

import base64
import hashlib

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
from waas.modules.solana.signing import UnavailableEd25519Signer
from waas.modules.ton import addresses, cells, service
from waas.modules.ton import indexing as ton_indexing
from waas.modules.ton import wallet as wallet_v4
from waas.modules.ton.chains import TonChain
from waas.modules.ton.models import TonTransaction
from waas.modules.ton.provider import BroadcastRejected, ProviderUnavailable
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db

TEST_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
TEST_PUBLIC = TEST_PRIVATE.public_key().public_bytes_raw()
OWNER_RAW = wallet_v4.wallet_address_raw(public_key=TEST_PUBLIC)
SENDER_RAW = "0:" + "33" * 32
DEST_RAW = "0:" + "22" * 32
DEST_FRIENDLY = addresses.raw_to_friendly(DEST_RAW, bounceable=True)
USDT_MASTER_RAW = addresses.normalize("EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs")


class TestSigner:
    """TEST-ONLY signer double (single key). Never production."""

    def wallet_public_key(self, wallet) -> bytes:
        return TEST_PUBLIC

    def sign_message(self, wallet, message: bytes) -> bytes:
        return TEST_PRIVATE.sign(message)


class FakeTonProvider:
    def __init__(self, network, *, send_mode: str = "ok", state: str = "active") -> None:
        self.chain = TonChain(network=network, endpoints=("memory://",))
        self.send_mode = send_mode
        self.state = state
        self.seqno = 0
        self.sent_bocs: list[bytes] = []
        self.by_message: dict[str, dict] = {}
        self.txs: dict[str, list[dict]] = {}
        self.master_seqno = 5000

    def jetton_wallet_for(self, owner_raw: str, master_raw: str = USDT_MASTER_RAW) -> str:
        return "0:" + hashlib.sha256(f"jw:{master_raw}:{owner_raw}".encode()).hexdigest()

    # provider surface ----------------------------------------------
    def get_account_state(self, raw_address: str) -> str:
        return self.state

    def get_balance(self, raw_address: str) -> int:
        return 0

    def get_seqno(self, raw_address: str) -> int:
        return self.seqno

    def get_masterchain_seqno(self) -> int:
        return self.master_seqno

    def get_jetton_wallet_address(self, *, master_raw: str, owner_raw: str) -> str:
        return self.jetton_wallet_for(owner_raw, master_raw)

    def get_transactions(self, raw_address: str, *, limit: int = 50) -> list[dict]:
        return list(reversed(self.txs.get(raw_address, [])))  # newest first, like the API

    def find_transaction_by_message(self, message_hash_hex: str) -> dict | None:
        return self.by_message.get(message_hash_hex)

    def send_boc_return_hash(self, boc: bytes) -> str:
        if self.send_mode == "reject":
            raise BroadcastRejected("cannot apply external message")
        if self.send_mode == "down":
            raise ProviderUnavailable("toncenter unreachable")
        self.sent_bocs.append(boc)
        return cells.Cell.from_boc(boc).hash().hex()


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    user = get_user_model().objects.create_user(email="ton@example.com", password="x" * 12)
    org = Organization.objects.create(name="Ton Org", slug="ton-org")
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=user
    )
    ton = BlockchainNetwork.objects.get(slug="ton")
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    service.register_wallet_ton_addresses(wallet=wallet, ed25519_public_key=TEST_PUBLIC)
    return {
        "project": project, "wallet": wallet, "ton": ton,
        "native": Asset.objects.get(network=ton, symbol="TON"),
        "usdt": Asset.objects.get(network=ton, symbol="USDT"),
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
        "wallet": ctx["wallet"], "network": ctx["ton"], "asset": ctx["native"],
        "to_address": DEST_FRIENDLY, "amount": 2_000_000_000,
        "idempotency_key": "wd-ton-1", "signer": TestSigner(), "provider": provider,
    }
    params.update(overrides)
    return service.execute_withdrawal(**params)


def success_tx(tx_hash: str = "ab" * 32) -> dict:
    return {
        "hash": tx_hash,
        "total_fees": "1500000",
        "mc_block_seqno": 5001,
        "description": {
            "compute_ph": {"success": True, "exit_code": 0},
            "action_ph": {"success": True},
        },
        "in_msg": {},
    }


# ---------------------------------------------------------- withdrawals


def test_native_withdrawal_round_trip(ctx) -> None:
    credit(ctx, ctx["native"], 5_000_000_000)
    provider = FakeTonProvider(ctx["ton"])
    tx = withdraw(ctx, provider)
    assert tx.status == TonTransaction.Status.BROADCAST
    assert tx.seqno == 0
    # The broadcast BoC parses back: external message -> body ->
    # the signature verifies over the signing-cell hash with the
    # wallet key (the exact check the wallet contract performs).
    external = cells.Cell.from_boc(provider.sent_bocs[0])
    ext_slice = external.begin_parse()
    assert ext_slice.read_uint(2) == 0b10
    body = external.refs[-1]
    signature = body.bits[:64]
    signing_cell = cells.Cell(body.bits[64:], body.bit_len - 512, body.refs)
    TEST_PRIVATE.public_key().verify(signature, signing_cell.hash())
    assert tx.external_message_hash == external.hash().hex()

    provider.by_message[tx.external_message_hash] = success_tx()
    tx = service.confirm_transaction(tx=tx, provider=provider)
    assert tx.status == TonTransaction.Status.CONFIRMED
    assert tx.total_fees_nano == 1_500_000
    assert balance(ctx, ctx["native"], AccountType.CUSTOMER_AVAILABLE) == 3_000_000_000
    assert balance(ctx, ctx["native"], AccountType.WITHDRAWAL_RESERVED) == 0
    assert ledger_services.trial_balance(ctx["project"], ctx["native"]) == 0


def test_jetton_withdrawal_addresses_jetton_wallet(ctx) -> None:
    credit(ctx, ctx["usdt"], 1_000_000)
    provider = FakeTonProvider(ctx["ton"])
    tx = withdraw(ctx, provider, asset=ctx["usdt"], amount=400_000, idempotency_key="wd-jtn-1")
    assert tx.status == TonTransaction.Status.BROADCAST
    assert tx.attached_ton_nano == 50_000_000
    external = cells.Cell.from_boc(provider.sent_bocs[0])
    body = external.refs[-1]
    signing_cell = cells.Cell(body.bits[64:], body.bit_len - 512, body.refs)
    internal = signing_cell.refs[0]
    internal_slice = internal.begin_parse()
    internal_slice.read_uint(1)  # int_msg_info
    internal_slice.read_bit()
    internal_slice.read_bit()
    internal_slice.read_bit()
    internal_slice.read_address()  # src none
    destination = internal_slice.read_address()
    assert destination == provider.jetton_wallet_for(OWNER_RAW)
    jetton_body = internal.refs[-1].begin_parse()
    assert jetton_body.read_uint(32) == wallet_v4.JETTON_TRANSFER_OP
    jetton_body.read_uint(64)
    assert jetton_body.read_coins() == 400_000
    assert jetton_body.read_address() == DEST_RAW


def test_signer_unavailable_and_rejection_release(ctx) -> None:
    credit(ctx, ctx["native"], 5_000_000_000)
    provider = FakeTonProvider(ctx["ton"])
    tx = withdraw(ctx, provider, signer=UnavailableEd25519Signer())
    assert tx.status == TonTransaction.Status.FAILED
    rejected = withdraw(
        ctx, FakeTonProvider(ctx["ton"], send_mode="reject"), idempotency_key="wd-ton-2"
    )
    assert rejected.status == TonTransaction.Status.FAILED
    down = withdraw(
        ctx, FakeTonProvider(ctx["ton"], send_mode="down"), idempotency_key="wd-ton-3"
    )
    assert down.status == TonTransaction.Status.DROPPED
    assert balance(ctx, ctx["native"], AccountType.WITHDRAWAL_RESERVED) == 2_000_000_000
    assert balance(ctx, ctx["native"], AccountType.CUSTOMER_AVAILABLE) == 3_000_000_000


def test_failed_execution_releases(ctx) -> None:
    credit(ctx, ctx["native"], 5_000_000_000)
    provider = FakeTonProvider(ctx["ton"])
    tx = withdraw(ctx, provider)
    provider.by_message[tx.external_message_hash] = {
        "hash": "cd" * 32, "total_fees": "900000", "mc_block_seqno": 5001,
        "description": {
            "compute_ph": {"success": False, "exit_code": 34},
            "action_ph": {"success": False},
        },
        "in_msg": {},
    }
    tx = service.confirm_transaction(tx=tx, provider=provider)
    assert tx.status == TonTransaction.Status.REVERTED
    assert balance(ctx, ctx["native"], AccountType.CUSTOMER_AVAILABLE) == 5_000_000_000


def test_blacklisted_destination_refused(ctx) -> None:
    BlacklistEntry.objects.create(
        scope="platform", network=ctx["ton"],
        address=DEST_FRIENDLY, normalized_address=DEST_RAW,
        reason="test", created_by=ctx["user"],
    )
    provider = FakeTonProvider(ctx["ton"])
    with pytest.raises(service.TonServiceError):
        withdraw(ctx, provider)
    assert TonTransaction.objects.count() == 0


# ------------------------------------------------------------ deposits


def _tx(lt: int, hash_byte: str, in_msg: dict) -> dict:
    return {
        "transaction_id": {
            "lt": str(lt),
            "hash": base64.b64encode(bytes.fromhex(hash_byte * 32)).decode(),
        },
        "in_msg": in_msg,
    }


def _in_msg(*, source: str = "", value: int = 0, body: cells.Cell | None = None,
            bounced: bool = False) -> dict:
    msg = {"source": source, "value": str(value), "bounced": bounced}
    if body is not None:
        msg["body"] = base64.b64encode(body.to_boc()).decode()
    return msg


def test_ton_deposit_scanning(ctx) -> None:
    provider = FakeTonProvider(ctx["ton"])
    jetton_raw = provider.jetton_wallet_for(OWNER_RAW)
    notification_body = (
        cells.begin_cell()
        .store_uint(wallet_v4.JETTON_NOTIFICATION_OP, 32)
        .store_uint(0, 64)
        .store_coins(777)
        .store_address(SENDER_RAW)
        .store_bit(0)
        .end_cell()
    )
    excess_body = (
        cells.begin_cell().store_uint(wallet_v4.EXCESSES_OP, 32).store_uint(0, 64).end_cell()
    )
    # Wallet account history: own external tx (skip), a plain TON
    # deposit, a jetton notification carrying TON value (NOT a
    # native deposit), an excess return (skip).
    provider.txs[OWNER_RAW] = [
        _tx(100, "aa", _in_msg(source="", value=0)),
        _tx(101, "bb", _in_msg(
            source=addresses.raw_to_friendly(SENDER_RAW, bounceable=True),
            value=3_000_000_000,
        )),
        _tx(102, "cc", _in_msg(
            source=addresses.raw_to_friendly(jetton_raw, bounceable=True),
            value=900_000, body=notification_body,
        )),
        _tx(103, "dd", _in_msg(
            source=addresses.raw_to_friendly(jetton_raw, bounceable=True),
            value=800_000, body=excess_body,
        )),
    ]
    # Jetton wallet history: a real internal_transfer deposit and
    # a bounced one (must not credit).
    transfer_body = (
        cells.begin_cell()
        .store_uint(wallet_v4.JETTON_INTERNAL_TRANSFER_OP, 32)
        .store_uint(0, 64)
        .store_coins(250_000)
        .store_address(SENDER_RAW)
        .store_address(OWNER_RAW)
        .store_coins(1)
        .store_bit(0)
        .end_cell()
    )
    provider.txs[jetton_raw] = [
        _tx(200, "ee", _in_msg(
            source=addresses.raw_to_friendly("0:" + "44" * 32, bounceable=True),
            value=50_000_000, body=transfer_body,
        )),
        _tx(201, "ff", _in_msg(
            source=addresses.raw_to_friendly("0:" + "44" * 32, bounceable=True),
            value=50_000_000, body=transfer_body, bounced=True,
        )),
    ]
    report = ton_indexing.scan_ton_once(network=ctx["ton"], provider=provider)
    assert report.deposits_detected == 2
    deposits = list(ObservedDeposit.objects.order_by("asset__symbol"))
    assert len(deposits) == 2
    ton_dep = next(d for d in deposits if d.asset.symbol == "TON")
    usdt_dep = next(d for d in deposits if d.asset.symbol == "USDT")
    assert int(ton_dep.amount) == 3_000_000_000
    assert ton_dep.from_address == SENDER_RAW
    assert int(usdt_dep.amount) == 250_000
    assert usdt_dep.from_address == SENDER_RAW  # the owner inside the payload
    assert balance(ctx, ctx["native"], AccountType.CUSTOMER_AVAILABLE) == 3_000_000_000
    assert balance(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE) == 250_000
    # Replay: cursors make the second pass a no-op.
    report = ton_indexing.scan_ton_once(network=ctx["ton"], provider=provider)
    assert report.deposits_detected == 0
    assert ObservedDeposit.objects.count() == 2
