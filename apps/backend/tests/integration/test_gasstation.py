"""Gas station: a token withdrawal/sweep from a wallet with no
native coin defers (never fails) while a top-up from the project's
funding wallet is broadcast through the normal pipeline; the next
pass proceeds once the balance has landed. Native transfers,
disabled stations, funded wallets and unreadable balances pass
through untouched.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from tests.conftest import auth_headers
from waas.modules.assets.models import Asset
from waas.modules.evm import keys as evm_keys
from waas.modules.evm.models import EvmTransaction
from waas.modules.gasstation.models import GasStation, GasTopUp
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import dispatch, services
from waas.modules.operations.models import WithdrawalPolicy, WithdrawalRequest
from waas.modules.organizations.models import Membership, Organization
from waas.modules.projects.models import Project
from waas.modules.sweeps import services as sweep_services
from waas.modules.wallets import services as wallet_services
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db

DEST = "0x3535353535353535353535353535353535353535"
MIN_BALANCE = 500_000_000_000_000
TOPUP = 2_000_000_000_000_000
FUNDING_SEED = 8_000_000_000_000_000


def _key_material(seed: int):
    key = ec.derive_private_key(int.from_bytes(bytes([seed]) * 32, "big"), ec.SECP256K1())
    numbers = key.public_key().public_numbers()
    pubkey = numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    return key, pubkey, evm_keys.address_from_public_key(pubkey)


TENANT_KEY, TENANT_PUB, TENANT_ADDR = _key_material(0x22)
FUND_KEY, FUND_PUB, FUND_ADDR = _key_material(0x44)


class MultiSigner:
    """TEST-ONLY signer double keyed per wallet. Never production."""

    def __init__(self, keys_by_wallet):
        self.keys = keys_by_wallet

    def wallet_public_key(self, wallet) -> bytes:
        return self.keys[wallet.id][1]

    def sign_digest(self, wallet, digest: bytes):
        der = self.keys[wallet.id][0].sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return utils.decode_dss_signature(der)


class FakeProvider:
    """EvmProvider double with an on-chain balance book."""

    def __init__(self, network) -> None:
        from waas.modules.evm.chains import EvmChain

        self.chain = EvmChain(network=network, endpoints=("memory://",))
        self.sent: list[bytes] = []
        self.receipt: dict | None = None
        self.current_block = 2000
        self.balances: dict[str, int] = {}

    def verify_chain(self) -> int:
        return self.chain.chain_id

    def get_transaction_count(self, address: str) -> int:
        return 0

    def fee_data(self):
        return (3_000_000_000, 1_000_000_000)

    def estimate_gas(self, **kwargs) -> int:
        return 50_000

    def send_raw_transaction(self, raw: bytes) -> str:
        self.sent.append(raw)
        return "0x" + (bytes([len(self.sent)]) * 32).hex()

    def get_receipt(self, tx_hash: str):
        return self.receipt

    def block_number(self) -> int:
        return self.current_block

    def get_balance(self, address: str) -> int:
        return self.balances.get(address.lower(), 0)


def _seed(project, asset, ref, amount, key):
    ledger_services.post_journal(
        project=project, asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset, account_type=AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": amount},
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset,
                account_type=AccountType.CUSTOMER_AVAILABLE, external_ref=ref),
             "side": "credit", "amount": amount},
        ],
        idempotency_key=key, operation_type="deposit", operation_id=key,
    )


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Gas Org", slug="gas-org")
    owner = User.objects.create_user(email="g-owner@example.com", password="x" * 12)
    approver = User.objects.create_user(email="g-appr@example.com", password="x" * 12)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    Membership.objects.create(
        organization=org, user=approver, role=Membership.Role.WITHDRAWAL_APPROVER
    )
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=owner
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    usdt = Asset.objects.get(network=network, symbol="USDT")
    native = Asset.objects.get(network=network, symbol="ETH")
    tenant = Wallet.objects.create(
        project=project, label="tenant", external_customer_id="cust_1"
    )
    wallet_services.record_derived_address(
        wallet=tenant, network=network, address=TENANT_ADDR, derivation_path="custodium/evm/1"
    )
    funding = Wallet.objects.create(
        project=project, label="gas fund", external_customer_id="gasfund"
    )
    wallet_services.record_derived_address(
        wallet=funding, network=network, address=FUND_ADDR, derivation_path="custodium/evm/2"
    )
    _seed(project, usdt, "cust_1", 1_000_000, "seed:usdt")
    _seed(project, native, "gasfund", FUNDING_SEED, "seed:eth")
    signer = MultiSigner({tenant.id: (TENANT_KEY, TENANT_PUB), funding.id: (FUND_KEY, FUND_PUB)})
    return {
        "org": org, "project": project, "network": network, "usdt": usdt,
        "native": native, "tenant": tenant, "funding": funding,
        "owner": owner, "approver": approver, "signer": signer,
    }


def factories(ctx, provider) -> dispatch.Factories:
    return dispatch.Factories(
        provider=lambda network: provider,
        ecdsa_signer=lambda: ctx["signer"],
        ed25519_signer=lambda: ctx["signer"],
    )


def make_station(ctx, **overrides) -> GasStation:
    params = {
        "project": ctx["project"], "network": ctx["network"],
        "funding_wallet": ctx["funding"], "enabled": True,
        "min_native_balance": MIN_BALANCE, "topup_amount": TOPUP,
        "max_topups_per_day": 100,
    }
    params.update(overrides)
    return GasStation.objects.create(**params)


def make_request(ctx, **overrides) -> WithdrawalRequest:
    WithdrawalPolicy.objects.get_or_create(
        project=ctx["project"], asset=None,
        defaults={"approvals_required": 0, "service_fee_flat": 1_000},
    )
    params = {
        "wallet": ctx["tenant"], "network": ctx["network"], "asset": ctx["usdt"],
        "destination_address": DEST, "amount": 100_000, "idempotency_key": "gas-req-1",
    }
    params.update(overrides)
    return services.create_withdrawal_request(**params)


def scope_balance(ctx, asset, account_type, ref) -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=asset, account_type=account_type, external_ref=ref
    )
    return int(ledger_services.account_balance(account))


SUCCESS_RECEIPT = {
    "status": "0x1", "blockNumber": hex(1999),
    "gasUsed": hex(21_000), "effectiveGasPrice": hex(1_000_000_000),
}


def test_token_withdrawal_defers_then_proceeds_after_topup(ctx) -> None:
    make_station(ctx)
    provider = FakeProvider(ctx["network"])
    request = make_request(ctx)
    assert request.status == WithdrawalRequest.Status.APPROVED

    first = services.dispatch_withdrawal(request=request, factories=factories(ctx, provider))
    assert first.status == WithdrawalRequest.Status.APPROVED, first.status_reason
    assert first.status_reason.startswith("awaiting gas")
    topup = GasTopUp.objects.get()
    assert topup.status == GasTopUp.Status.BROADCAST
    assert int(topup.amount) == TOPUP
    # Exactly one chain send so far: the top-up FROM the funding
    # wallet TO the tenant wallet. The USDT transfer never started.
    assert len(provider.sent) == 1
    topup_tx = EvmTransaction.objects.get(idempotency_key=f"gas:wd:{request.id}")
    assert topup_tx.to_address.lower() == TENANT_ADDR.lower()
    # The service fee charged for the deferred attempt was reversed.
    assert scope_balance(ctx, ctx["usdt"], AccountType.PLATFORM_FEES_PAYABLE, "") == 0
    assert scope_balance(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE, "cust_1") == 1_000_000

    # The top-up lands on-chain (13 confirmations over the receipt
    # block; ethereum requires 12).
    provider.balances[TENANT_ADDR.lower()] = TOPUP
    provider.receipt = SUCCESS_RECEIPT
    provider.current_block = 2011
    second = services.dispatch_withdrawal(request=request, factories=factories(ctx, provider))
    assert second.status == WithdrawalRequest.Status.BROADCAST
    assert len(provider.sent) == 2
    topup.refresh_from_db()
    assert topup.status == GasTopUp.Status.CONFIRMED
    # The funding wallet's reservation settled for exactly the
    # top-up amount; the project's native trial balance is zero.
    assert scope_balance(ctx, ctx["native"], AccountType.WITHDRAWAL_RESERVED, "gasfund") == 0
    assert scope_balance(ctx, ctx["native"], AccountType.CUSTOMER_AVAILABLE, "gasfund") == (
        FUNDING_SEED - TOPUP
    )
    assert ledger_services.trial_balance(ctx["project"], ctx["native"]) == 0


def test_native_withdrawal_never_triggers_station(ctx) -> None:
    make_station(ctx)
    _seed(ctx["project"], ctx["native"], "cust_1", MIN_BALANCE * 4, "seed:tenant-eth")
    provider = FakeProvider(ctx["network"])
    request = make_request(ctx, asset=ctx["native"], amount=MIN_BALANCE, idempotency_key="n-1")
    out = services.dispatch_withdrawal(request=request, factories=factories(ctx, provider))
    assert out.status == WithdrawalRequest.Status.BROADCAST
    assert GasTopUp.objects.count() == 0


def test_disabled_station_and_funded_wallet_pass_through(ctx) -> None:
    make_station(ctx, enabled=False)
    provider = FakeProvider(ctx["network"])
    request = make_request(ctx, idempotency_key="d-1")
    out = services.dispatch_withdrawal(request=request, factories=factories(ctx, provider))
    assert out.status == WithdrawalRequest.Status.BROADCAST
    assert GasTopUp.objects.count() == 0

    GasStation.objects.update(enabled=True)
    provider.balances[TENANT_ADDR.lower()] = MIN_BALANCE * 2
    request2 = make_request(ctx, idempotency_key="d-2")
    out2 = services.dispatch_withdrawal(request=request2, factories=factories(ctx, provider))
    assert out2.status == WithdrawalRequest.Status.BROADCAST
    assert GasTopUp.objects.count() == 0


def test_daily_cap_defers_without_topup(ctx) -> None:
    make_station(ctx, max_topups_per_day=0)
    provider = FakeProvider(ctx["network"])
    request = make_request(ctx, idempotency_key="cap-1")
    out = services.dispatch_withdrawal(request=request, factories=factories(ctx, provider))
    assert out.status == WithdrawalRequest.Status.APPROVED
    assert "cap" in out.status_reason
    assert GasTopUp.objects.count() == 0
    assert provider.sent == []


def test_sweep_defers_and_resumes_with_same_snapshot(ctx) -> None:
    from waas.modules.sweeps import resolver  # noqa: F401  (documents the seam)
    from waas.modules.sweeps.models import Sweep

    make_station(ctx)
    sweep_services.register_endpoint(
        project=ctx["project"], url="https://tenant.example/resolve",
        actor=ctx["owner"], dns_resolver=lambda host: ["93.184.216.34"],
    )
    sweep = sweep_services.create_sweep(
        wallet=ctx["tenant"], network=ctx["network"], asset=ctx["usdt"],
        idempotency_key="gas-sweep-1",
        requested_by_type="user", requested_by_id=str(ctx["owner"].id),
    )
    import httpx

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=DEST.encode())
        ),
        follow_redirects=False,
    )
    kwargs = {"http_client": client, "dns_resolver": lambda host: ["93.184.216.34"]}
    provider = FakeProvider(ctx["network"])
    processed = sweep_services.process_sweep(
        sweep=sweep, factories=factories(ctx, provider), resolver_kwargs=kwargs
    )
    assert processed.status == Sweep.Status.AWAITING_APPROVAL
    approved = sweep_services.record_sweep_approval(
        sweep=processed, approver=ctx["approver"], decision="approved"
    )
    deferred = sweep_services.process_sweep(
        sweep=approved, factories=factories(ctx, provider), resolver_kwargs=kwargs
    )
    assert deferred.status == Sweep.Status.RESOLVED
    assert deferred.status_reason.startswith("awaiting gas")
    assert GasTopUp.objects.count() == 1
    provider.balances[TENANT_ADDR.lower()] = TOPUP
    provider.receipt = SUCCESS_RECEIPT
    executed = sweep_services.process_sweep(
        sweep=deferred, factories=factories(ctx, provider)
    )
    assert executed.status == Sweep.Status.BROADCAST


def test_station_api_validation(ctx) -> None:
    from waas.modules.identity.models import DashboardToken

    client = Client()
    _, raw_token = DashboardToken.issue(ctx["owner"])
    headers = auth_headers(raw_token)
    other = Wallet.objects.create(project=Project.objects.create(
        organization=ctx["org"], name="Other", environment="sandbox", created_by=ctx["owner"]
    ), label="foreign")
    bad = client.put(
        "/api/v1/gas-stations",
        data={
            "project_id": str(ctx["project"].id), "network": "ethereum",
            "funding_wallet_id": str(other.id),
            "min_native_balance": "100", "topup_amount": "200",
        },
        content_type="application/json", **headers,
    )
    assert bad.status_code == 422  # funding wallet must be same-project
    ok = client.put(
        "/api/v1/gas-stations",
        data={
            "project_id": str(ctx["project"].id), "network": "ethereum",
            "funding_wallet_id": str(ctx["funding"].id),
            "min_native_balance": str(MIN_BALANCE), "topup_amount": str(TOPUP),
        },
        content_type="application/json", **headers,
    )
    assert ok.status_code == 200
    listing = client.get(
        "/api/v1/gas-stations", {"project_id": str(ctx["project"].id)}, **headers
    )
    assert listing.status_code == 200
    assert listing.json()[0]["network"] == "ethereum"
