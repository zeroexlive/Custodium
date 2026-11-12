"""Phase 5 indexing: EVM deposit detection, confirmation crediting,
reorg reversal, exactly-once semantics under replay, blacklist
holds, reconciliation, and the transaction lookup API.

The chain is an in-memory double implementing the provider surface
the scanner uses; blocks are content-addressed by a salt so forks
get different hashes for the same heights.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from tests.conftest import auth_headers, make_org_project, register_user
from waas.modules.assets.models import Asset
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.evm import keys
from waas.modules.evm.chains import EvmChain
from waas.modules.indexing import services
from waas.modules.indexing.models import ChainCursor, ObservedDeposit, ScannedBlock
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Wallet
from waas.modules.wallets.services import record_derived_address

pytestmark = pytest.mark.django_db

WATCHED = "0x1111111111111111111111111111111111111111"
SENDER = "0x3333333333333333333333333333333333333333"
USDT_ETH = "0xdac17f958d2ee523a2206206994597c13d831ec7"
TRANSFER_TOPIC = services.TRANSFER_TOPIC


def _hash(salt: str, number: int) -> str:
    return "0x" + keys.keccak256(f"{salt}:{number}".encode()).hex()


def _txhash(salt: str) -> str:
    return "0x" + keys.keccak256(f"tx:{salt}".encode()).hex()


class FakeChain:
    """In-memory EVM chain double with fork support."""

    def __init__(self, network: BlockchainNetwork) -> None:
        self.chain = EvmChain(network=network, endpoints=("memory://",))
        self.network = network
        self.blocks: dict[int, dict] = {}
        self.receipts: dict[str, dict] = {}
        self.logs: dict[int, list[dict]] = {}
        self.head = -1
        self.salt = "a"

    # provider surface ------------------------------------------------
    def verify_chain(self) -> int:
        return self.network.chain_id

    def block_number(self) -> int:
        return self.head

    def get_block(self, number: int) -> dict | None:
        return self.blocks.get(number)

    def get_block_hash(self, number: int) -> str | None:
        block = self.blocks.get(number)
        return None if block is None else block["hash"]

    def get_receipt(self, tx_hash: str) -> dict | None:
        return self.receipts.get(tx_hash.lower())

    def get_logs(self, *, addresses, topics, from_block, to_block) -> list[dict]:
        out = []
        wanted = {a.lower() for a in addresses}
        for number in range(from_block, to_block + 1):
            for log in self.logs.get(number, []):
                if log["address"].lower() in wanted and log["topics"][0] == topics[0]:
                    out.append(log)
        return out

    # chain construction ----------------------------------------------
    def add_block(self, *, txs=(), logs=(), salt: str | None = None) -> int:
        number = self.head + 1
        block_hash = _hash(salt or self.salt, number)
        parent = self.blocks[number - 1]["hash"] if number > 0 else "0x" + "00" * 32
        block = {
            "number": hex(number),
            "hash": block_hash,
            "parentHash": parent,
            "transactions": list(txs),
        }
        self.blocks[number] = block
        self.logs[number] = list(logs)
        for tx in txs:
            self.receipts[tx["hash"].lower()] = {
                "status": tx.get("status", "0x1"),
                "blockNumber": hex(number),
            }
        self.head = number
        return number

    def native_tx(self, *, to: str, value: int, salt: str, status: str = "0x1") -> dict:
        return {
            "hash": _txhash(salt),
            "from": SENDER,
            "to": to,
            "value": hex(value),
            "status": status,
        }

    def transfer_log(self, *, contract: str, to: str, amount: int, salt: str, index: int = 0) -> dict:
        return {
            "address": contract,
            "topics": [
                TRANSFER_TOPIC,
                "0x" + "00" * 12 + SENDER[2:],
                "0x" + "00" * 12 + to[2:].lower(),
            ],
            "data": hex(amount),
            "transactionHash": _txhash(salt),
            "logIndex": hex(index),
        }

    def reorg(self, from_number: int, *, salt: str = "b") -> None:
        """Replace every block from `from_number` with empty fork
        blocks carrying different hashes."""
        for number in range(from_number, self.head + 1):
            block_hash = _hash(salt, number)
            self.blocks[number] = {
                "number": hex(number),
                "hash": block_hash,
                "parentHash": self.blocks[number - 1]["hash"] if number > 0 else "0x" + "00" * 32,
                "transactions": [],
            }
            self.logs[number] = []


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    user = get_user_model().objects.create_user(email="idx@example.com", password="x" * 12)
    from waas.modules.organizations.models import Organization
    from waas.modules.projects.models import Project

    org = Organization.objects.create(name="Idx Org", slug="idx-org")
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=user
    )
    sepolia = BlockchainNetwork.objects.get(slug="ethereum-sepolia")
    sepolia.confirmations_required = 3
    sepolia.save(update_fields=["confirmations_required"])
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    record_derived_address(wallet=wallet, network=sepolia, address=WATCHED)
    eth = Asset.objects.get(network=sepolia, symbol="ETH")
    return {"project": project, "wallet": wallet, "sepolia": sepolia, "eth": eth, "user": user}


def balance(ctx, asset, account_type, ref="cust_1") -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=asset, account_type=account_type, external_ref=ref
    )
    return ledger_services.account_balance(account)


def scan(ctx, chain, **kwargs):
    return services.scan_once(network=ctx["sepolia"], provider=chain, **kwargs)


def test_native_deposit_lifecycle(ctx) -> None:
    chain = FakeChain(ctx["sepolia"])
    for _ in range(4):
        chain.add_block()
    chain.add_block(txs=[chain.native_tx(to=WATCHED, value=10**17, salt="dep1")])  # block 4
    report = scan(ctx, chain)
    assert report.deposits_detected == 1
    deposit = ObservedDeposit.objects.get()
    assert deposit.status == ObservedDeposit.Status.PENDING
    # Observed stage: pending balances only.
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_PENDING) == 10**17
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 0
    assert balance(ctx, ctx["eth"], AccountType.CUSTODY_PENDING, ref="") == 10**17

    chain.add_block()
    chain.add_block()  # head 6 -> 3 confirmations for block 4
    report = scan(ctx, chain)
    assert report.deposits_credited == 1
    deposit.refresh_from_db()
    assert deposit.status == ObservedDeposit.Status.CREDITED
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_PENDING) == 0
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 10**17
    assert balance(ctx, ctx["eth"], AccountType.CUSTODY_PENDING, ref="") == 0
    assert balance(ctx, ctx["eth"], AccountType.CUSTODY_ONCHAIN, ref="") == 10**17
    assert ledger_services.trial_balance(ctx["project"], ctx["eth"]) == 0


def test_replay_never_double_credits(ctx) -> None:
    chain = FakeChain(ctx["sepolia"])
    chain.add_block(txs=[chain.native_tx(to=WATCHED, value=5 * 10**16, salt="dep1")])
    chain.add_block()
    chain.add_block()
    scan(ctx, chain)
    assert ObservedDeposit.objects.count() == 1
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 5 * 10**16
    # Full replay from scratch (cursor wiped): the same chain events
    # must produce no new rows and no new journal entries.
    ChainCursor.objects.all().delete()
    ScannedBlock.objects.all().delete()
    scan(ctx, chain)
    assert ObservedDeposit.objects.count() == 1
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 5 * 10**16
    assert ledger_services.trial_balance(ctx["project"], ctx["eth"]) == 0


def test_token_deposit_via_transfer_log(ctx) -> None:
    ethereum = BlockchainNetwork.objects.get(slug="ethereum")
    ethereum.confirmations_required = 2
    ethereum.save(update_fields=["confirmations_required"])
    record_derived_address(wallet=ctx["wallet"], network=ethereum, address=WATCHED)
    usdt = Asset.objects.get(network=ethereum, symbol="USDT")
    chain = FakeChain(ethereum)
    chain.add_block(logs=[chain.transfer_log(contract=USDT_ETH, to=WATCHED, amount=250_000_000, salt="usdt1")])
    chain.add_block()
    services.scan_once(network=ethereum, provider=chain)
    deposit = ObservedDeposit.objects.get(network=ethereum)
    assert deposit.asset == usdt
    assert int(deposit.amount) == 250_000_000
    assert deposit.status == ObservedDeposit.Status.CREDITED
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=usdt,
        account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1",
    )
    assert ledger_services.account_balance(account) == 250_000_000


def test_failed_transaction_is_not_a_deposit(ctx) -> None:
    chain = FakeChain(ctx["sepolia"])
    chain.add_block(txs=[chain.native_tx(to=WATCHED, value=10**17, salt="fail", status="0x0")])
    scan(ctx, chain)
    assert ObservedDeposit.objects.count() == 0


def test_reorg_before_credit_reverses_observation(ctx) -> None:
    chain = FakeChain(ctx["sepolia"])
    chain.add_block(txs=[chain.native_tx(to=WATCHED, value=10**17, salt="dep1")])  # block 0
    chain.add_block()  # 2 confirmations: still pending (needs 3)
    scan(ctx, chain)
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_PENDING) == 10**17
    chain.reorg(0)
    report = scan(ctx, chain)
    assert report.reorg_depth == 2
    deposit = ObservedDeposit.objects.get()
    assert deposit.status == ObservedDeposit.Status.REORGED_OUT
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_PENDING) == 0
    assert balance(ctx, ctx["eth"], AccountType.CUSTODY_PENDING, ref="") == 0
    assert ledger_services.trial_balance(ctx["project"], ctx["eth"]) == 0


def test_reorg_after_credit_reverses_everything(ctx) -> None:
    chain = FakeChain(ctx["sepolia"])
    chain.add_block(txs=[chain.native_tx(to=WATCHED, value=10**17, salt="dep1")])
    chain.add_block()
    chain.add_block()
    scan(ctx, chain)
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 10**17
    chain.reorg(0)
    scan(ctx, chain)
    deposit = ObservedDeposit.objects.get()
    assert deposit.status == ObservedDeposit.Status.REORGED_OUT
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 0
    assert balance(ctx, ctx["eth"], AccountType.CUSTODY_ONCHAIN, ref="") == 0
    assert ledger_services.trial_balance(ctx["project"], ctx["eth"]) == 0


def test_blacklisted_sender_is_held(ctx) -> None:
    BlacklistEntry.objects.create(
        scope="platform", network=ctx["sepolia"], address=SENDER,
        normalized_address=SENDER.lower(), reason="test", created_by=ctx["user"],
    )
    chain = FakeChain(ctx["sepolia"])
    chain.add_block(txs=[chain.native_tx(to=WATCHED, value=10**17, salt="dep1")])
    chain.add_block()
    chain.add_block()
    chain.add_block()
    scan(ctx, chain)
    deposit = ObservedDeposit.objects.get()
    assert deposit.held is True
    assert deposit.status == ObservedDeposit.Status.PENDING
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 0
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_PENDING) == 10**17


def test_reconciliation_balanced(ctx) -> None:
    chain = FakeChain(ctx["sepolia"])
    chain.add_block(txs=[chain.native_tx(to=WATCHED, value=10**17, salt="dep1")])
    chain.add_block()
    chain.add_block()
    scan(ctx, chain)
    report = services.reconciliation_report(network=ctx["sepolia"])
    eth_row = next(r for r in report["assets"] if r["asset"] == "ETH")
    assert eth_row["balanced"] is True
    assert eth_row["expected_custody"] == str(10**17)
    assert eth_row["ledger_custody"] == str(10**17)


# ------------------------------------------------------------- lookup API


def test_lookup_api_finds_deposit_and_hides_other_tenants(client: Client, ctx) -> None:
    chain = FakeChain(ctx["sepolia"])
    tx = chain.native_tx(to=WATCHED, value=10**17, salt="dep1")
    chain.add_block(txs=[tx])
    scan(ctx, chain)

    owner = register_user(client, "owner@example.com")
    token = owner["token"]
    mine = make_org_project(client, token, "a")
    # The ctx deposit belongs to a different tenant. Per the lookup
    # design (docs/api/transaction-lookup.md §4), the caller gets the
    # public on-chain projection only: belongs_to_tenant=false, no
    # matched addresses, no tenant_record — never the owner's data,
    # and never a distinguishing 404.
    response = client.get(
        "/api/v1/transactions/lookup",
        {"network": "ethereum-sepolia", "hash": tx["hash"], "project_id": mine["project"]["id"]},
        **auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["belongs_to_tenant"] is False
    assert body["indexed"] is True
    assert body["matched_addresses"] == []
    assert "tenant_record" not in body
    assert body["transfers"][0]["amount_base_units"] == str(10**17)

    # A hash that is not indexed at all is a plain 404.
    response = client.get(
        "/api/v1/transactions/lookup",
        {"network": "ethereum-sepolia", "hash": "0x" + "ab" * 32,
         "project_id": mine["project"]["id"]},
        **auth_headers(token),
    )
    assert response.status_code == 404

    # Malformed hash -> 422 before any lookup.
    response = client.get(
        "/api/v1/transactions/lookup",
        {"network": "ethereum-sepolia", "hash": "0xabc",
         "project_id": mine["project"]["id"]},
        **auth_headers(token),
    )
    assert response.status_code == 422

    # The deposits list stays strictly tenant-scoped (404).
    response = client.get(
        f"/api/v1/wallets/{ctx['wallet'].id}/deposits",
        {"project_id": mine["project"]["id"]},
        **auth_headers(token),
    )
    assert response.status_code == 404  # wallet belongs to another tenant

    # The owning tenant sees the full projection: a fresh user added
    # as a member of the ctx organization finds the deposit with its
    # wallet/customer attribution and a tenant_record.
    from waas.modules.organizations.models import Membership

    member = register_user(client, "member@example.com")
    member_user = get_user_model().objects.get(email="member@example.com")
    Membership.objects.create(
        user=member_user, organization=ctx["wallet"].project.organization, role="owner"
    )
    response = client.get(
        "/api/v1/transactions/lookup",
        {"network": "ethereum-sepolia", "hash": tx["hash"]},
        **auth_headers(member["token"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["belongs_to_tenant"] is True
    assert body["tenant_record"]["type"] == "deposit"
    assert body["tenant_record"]["wallet_id"] == str(ctx["wallet"].id)
    assert body["matched_addresses"][0]["external_customer_id"] == "cust_1"
    assert body["transfers"][0]["direction"] == "in"

    # And the wallet's deposit list works for the owner.
    response = client.get(
        f"/api/v1/wallets/{ctx['wallet'].id}/deposits",
        {"project_id": str(ctx["wallet"].project_id)},
        **auth_headers(member["token"]),
    )
    assert response.status_code == 200
    deposits = response.json()["deposits"]
    assert len(deposits) == 1
    assert deposits[0]["tx_hash"] == tx["hash"].lower()
