"""EVM withdrawal pipeline (Phase 4): reserve → build → sign →
broadcast → confirm → settle, with the ledger reconciling at every
step. Provider and signer are test doubles — the signer is a
TEST-ONLY single-key implementation (published test key); the
production signer port remains fail-closed (see the
signing-unavailable test, which is the behaviour real deployments
get today).
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from django.contrib.auth import get_user_model
from django.core.management import call_command

from waas.modules.assets.models import Asset
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.evm import service
from waas.modules.evm.chains import EvmChain
from waas.modules.evm.models import EvmTransaction
from waas.modules.evm.signing import UnavailableSigner
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Organization
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db

TEST_KEY = ec.derive_private_key(
    int.from_bytes(bytes.fromhex("46" * 32), "big"), ec.SECP256K1()
)
DEST = "0x2222222222222222222222222222222222222222"


class TestSigner:
    """TEST-ONLY signer double (single key). Never production."""

    def wallet_public_key(self, wallet) -> bytes:
        numbers = TEST_KEY.public_key().public_numbers()
        return numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")

    def sign_digest(self, wallet, digest: bytes) -> tuple[int, int]:
        der = TEST_KEY.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return utils.decode_dss_signature(der)


class FakeProvider:
    """In-memory provider double with the EvmProvider surface."""

    def __init__(self, chain: EvmChain, *, receipt_status: int = 1) -> None:
        self.chain = chain
        self.nonce = 0
        self.sent: list[bytes] = []
        self.receipt_status = receipt_status
        self.receipt_block = 100
        self.current_block = 100

    def verify_chain(self) -> int:
        return self.chain.chain_id

    def get_transaction_count(self, address: str) -> int:
        return self.nonce

    def fee_data(self) -> tuple[int, int]:
        return (30_000_000_000, 1_000_000_000)

    def estimate_gas(self, **kwargs) -> int:
        return 50_000

    def send_raw_transaction(self, raw: bytes) -> str:
        from waas.modules.evm.transactions import transaction_hash

        self.sent.append(raw)
        return "0x" + transaction_hash(raw).hex()

    def get_receipt(self, tx_hash: str) -> dict | None:
        if not self.sent:
            return None
        return {"status": hex(self.receipt_status), "blockNumber": hex(self.receipt_block)}

    def block_number(self) -> int:
        return self.current_block


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    user = get_user_model().objects.create_user(email="evm@example.com", password="x" * 12)
    org = Organization.objects.create(name="EVM Org", slug="evm-org")
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=user
    )
    sepolia = BlockchainNetwork.objects.get(slug="ethereum-sepolia")
    sepolia.confirmations_required = 3
    sepolia.save(update_fields=["confirmations_required"])
    wallet = Wallet.objects.create(
        project=project, label="ops", external_customer_id="cust_1"
    )
    eth = Asset.objects.get(network=sepolia, symbol="ETH")
    return {
        "project": project, "wallet": wallet, "sepolia": sepolia, "eth": eth,
        "org": org, "user": user,
    }


def fund(ctx, asset, amount: int, key: str) -> None:
    custody = ledger_services.get_or_create_account(
        project=ctx["project"], asset=asset, account_type=AccountType.CUSTODY_ONCHAIN
    )
    available = ledger_services.get_or_create_account(
        project=ctx["project"], asset=asset,
        account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1",
    )
    ledger_services.post_journal(
        project=ctx["project"], asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": custody, "side": "debit", "amount": amount},
            {"account": available, "side": "credit", "amount": amount},
        ],
        idempotency_key=key, operation_type="deposit", operation_id=key,
    )


def balance(ctx, asset, account_type, ref="cust_1") -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=asset, account_type=account_type, external_ref=ref
    )
    return ledger_services.account_balance(account)


def provider_for(ctx, network, **kwargs) -> FakeProvider:
    return FakeProvider(EvmChain(network=network, endpoints=("memory://",)), **kwargs)


def test_address_registration(ctx) -> None:
    signer = TestSigner()
    rows = service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=signer.wallet_public_key(ctx["wallet"])
    )
    assert len(rows) == 4  # ethereum, sepolia, bsc, bsc-testnet
    assert len({row.address for row in rows}) == 1  # one address on every EVM chain
    again = service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=signer.wallet_public_key(ctx["wallet"])
    )
    assert [r.id for r in again] == [r.id for r in rows]  # idempotent


def test_native_withdrawal_round_trip(ctx) -> None:
    fund(ctx, ctx["eth"], 10**18, "dep-1")
    service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=TestSigner().wallet_public_key(ctx["wallet"])
    )
    provider = provider_for(ctx, ctx["sepolia"])
    tx = service.execute_withdrawal(
        wallet=ctx["wallet"], network=ctx["sepolia"], asset=ctx["eth"],
        to_address=DEST, amount=10**17, idempotency_key="wd-1",
        signer=TestSigner(), provider=provider,
    )
    assert tx.status == EvmTransaction.Status.BROADCAST
    assert tx.tx_hash.startswith("0x") and len(tx.tx_hash) == 66
    assert len(provider.sent) == 1
    # Funds are reserved, not yet settled.
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 10**18 - 10**17
    assert balance(ctx, ctx["eth"], AccountType.WITHDRAWAL_RESERVED) == 10**17

    provider.current_block = 100 + 2  # 3 confirmations (100, 101, 102)
    tx = service.confirm_transaction(tx=tx, provider=provider)
    assert tx.status == EvmTransaction.Status.CONFIRMED
    assert balance(ctx, ctx["eth"], AccountType.WITHDRAWAL_RESERVED) == 0
    # Custody dropped by the settled amount: the money left.
    assert balance(ctx, ctx["eth"], AccountType.CUSTODY_ONCHAIN, ref="") == 10**18 - 10**17
    assert ledger_services.trial_balance(ctx["project"], ctx["eth"]) == 0

    # Re-confirming is a no-op.
    tx = service.confirm_transaction(tx=tx, provider=provider)
    assert tx.status == EvmTransaction.Status.CONFIRMED


def test_idempotent_reentry(ctx) -> None:
    fund(ctx, ctx["eth"], 10**18, "dep-1")
    service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=TestSigner().wallet_public_key(ctx["wallet"])
    )
    provider = provider_for(ctx, ctx["sepolia"])
    kwargs = dict(
        wallet=ctx["wallet"], network=ctx["sepolia"], asset=ctx["eth"],
        to_address=DEST, amount=10**17, idempotency_key="wd-dup",
        signer=TestSigner(), provider=provider,
    )
    first = service.execute_withdrawal(**kwargs)
    second = service.execute_withdrawal(**kwargs)
    assert first.id == second.id
    assert EvmTransaction.objects.count() == 1
    assert len(provider.sent) == 1  # broadcast exactly once


def test_signing_unavailable_releases_reservation(ctx) -> None:
    """The production reality today: no reviewed signer, so the
    pipeline must abort cleanly with funds fully restored."""
    fund(ctx, ctx["eth"], 10**18, "dep-1")
    service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=TestSigner().wallet_public_key(ctx["wallet"])
    )
    provider = provider_for(ctx, ctx["sepolia"])
    tx = service.execute_withdrawal(
        wallet=ctx["wallet"], network=ctx["sepolia"], asset=ctx["eth"],
        to_address=DEST, amount=10**17, idempotency_key="wd-nosigner",
        signer=UnavailableSigner(), provider=provider,
    )
    assert tx.status == EvmTransaction.Status.FAILED
    assert "signing unavailable" in tx.failure_reason
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 10**18
    assert balance(ctx, ctx["eth"], AccountType.WITHDRAWAL_RESERVED) == 0
    assert provider.sent == []


def test_insufficient_funds(ctx) -> None:
    fund(ctx, ctx["eth"], 10**16, "dep-1")
    service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=TestSigner().wallet_public_key(ctx["wallet"])
    )
    tx = service.execute_withdrawal(
        wallet=ctx["wallet"], network=ctx["sepolia"], asset=ctx["eth"],
        to_address=DEST, amount=10**17, idempotency_key="wd-poor",
        signer=TestSigner(), provider=provider_for(ctx, ctx["sepolia"]),
    )
    assert tx.status == EvmTransaction.Status.FAILED
    assert "reservation failed" in tx.failure_reason


def test_reverted_transaction_releases(ctx) -> None:
    fund(ctx, ctx["eth"], 10**18, "dep-1")
    service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=TestSigner().wallet_public_key(ctx["wallet"])
    )
    provider = provider_for(ctx, ctx["sepolia"], receipt_status=0)
    tx = service.execute_withdrawal(
        wallet=ctx["wallet"], network=ctx["sepolia"], asset=ctx["eth"],
        to_address=DEST, amount=10**17, idempotency_key="wd-revert",
        signer=TestSigner(), provider=provider,
    )
    assert tx.status == EvmTransaction.Status.BROADCAST
    tx = service.confirm_transaction(tx=tx, provider=provider)
    assert tx.status == EvmTransaction.Status.REVERTED
    assert balance(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE) == 10**18
    assert balance(ctx, ctx["eth"], AccountType.WITHDRAWAL_RESERVED) == 0


def test_blacklisted_destination_rejected(ctx) -> None:
    fund(ctx, ctx["eth"], 10**18, "dep-1")
    BlacklistEntry.objects.create(
        scope="platform", network=ctx["sepolia"], address=DEST,
        normalized_address=DEST.lower(), reason="test entry",
        created_by=ctx["user"],
    )
    with pytest.raises(service.EvmServiceError):
        service.execute_withdrawal(
            wallet=ctx["wallet"], network=ctx["sepolia"], asset=ctx["eth"],
            to_address=DEST, amount=10**17, idempotency_key="wd-blacklist",
            signer=TestSigner(), provider=provider_for(ctx, ctx["sepolia"]),
        )
    assert EvmTransaction.objects.count() == 0


def test_token_withdrawal_builds_erc20_call(ctx) -> None:
    bsc = BlockchainNetwork.objects.get(slug="bsc")
    usdt = Asset.objects.get(network=bsc, symbol="USDT")
    fund(ctx, usdt, 500_000_000_000_000_000_000, "dep-usdt")
    service.register_wallet_evm_addresses(
        wallet=ctx["wallet"], ecdsa_public_key=TestSigner().wallet_public_key(ctx["wallet"])
    )
    provider = provider_for(ctx, bsc)
    tx = service.execute_withdrawal(
        wallet=ctx["wallet"], network=bsc, asset=usdt,
        to_address=DEST, amount=25_000_000_000_000_000_000, idempotency_key="wd-usdt",
        signer=TestSigner(), provider=provider,
    )
    assert tx.status == EvmTransaction.Status.BROADCAST
    assert tx.is_token is True
    assert tx.gas_limit == 50_000  # from the estimator
    raw = bytes.fromhex(tx.raw_transaction[2:])
    assert raw[0] == 0x02  # type-2 envelope even on BSC
