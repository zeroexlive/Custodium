"""Phase 10 sweeps: the resolver rule (destinations ONLY from
the registered endpoint), SSRF/format defences, immutable
snapshots, and sweep accounting — penetration-style, per the
backlog exit criteria.
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from django.contrib.auth import get_user_model
from django.core.management import call_command

from waas.modules.assets.models import Asset
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.evm import keys as evm_keys
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import dispatch
from waas.modules.operations.models import WithdrawalPolicy
from waas.modules.organizations.models import Membership, Organization
from waas.modules.projects.models import Project
from waas.modules.sweeps import resolver, services
from waas.modules.sweeps.models import (
    ResolvedDestinationSnapshot,
    Sweep,
    SweepDestinationEndpoint,
    SweepPolicy,
)
from waas.modules.wallets import services as wallet_services
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db

_EC_KEY = ec.derive_private_key(int.from_bytes(b"\x22" * 32, "big"), ec.SECP256K1())
_NUMBERS = _EC_KEY.public_key().public_numbers()
TEST_PUBKEY = _NUMBERS.x.to_bytes(32, "big") + _NUMBERS.y.to_bytes(32, "big")
FROM = evm_keys.address_from_public_key(TEST_PUBKEY)
DEST = "0x3535353535353535353535353535353535353535"
DEST2 = "0x4545454545454545454545454545454545454545"
PUBLIC_DNS = lambda host: ["93.184.216.34"]  # noqa: E731 - test double


class TestSigner:
    """TEST-ONLY signer double. Never production."""

    def wallet_public_key(self, wallet) -> bytes:
        return TEST_PUBKEY

    def sign_digest(self, wallet, digest: bytes):
        der = _EC_KEY.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return utils.decode_dss_signature(der)


class FakeProvider:
    def __init__(self, network) -> None:
        from waas.modules.evm.chains import EvmChain

        self.chain = EvmChain(network=network, endpoints=("memory://",))
        self.sent: list[bytes] = []
        self.receipt: dict | None = None

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
        return "0x" + (b"\xcd" * 32).hex()

    def get_receipt(self, tx_hash: str):
        return self.receipt

    def block_number(self) -> int:
        return 2000


def factories(provider) -> dispatch.Factories:
    return dispatch.Factories(
        provider=lambda network: provider,
        ecdsa_signer=lambda: TestSigner(),
        ed25519_signer=lambda: TestSigner(),
    )


def endpoint_client(body: bytes, status: int = 200, headers: dict | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers=headers or {})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Sweep Org", slug="sweep-org")
    owner = User.objects.create_user(email="s-owner@example.com", password="x" * 12)
    approver = User.objects.create_user(email="s-appr@example.com", password="x" * 12)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    Membership.objects.create(
        organization=org, user=approver, role=Membership.Role.WITHDRAWAL_APPROVER
    )
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=owner
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    network.confirmations_required = 1
    network.save(update_fields=["confirmations_required"])
    asset = Asset.objects.get(network=network, symbol="USDT")
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    wallet_services.record_derived_address(
        wallet=wallet, network=network, address=FROM, derivation_path="custodium/evm/1"
    )
    wallet.refresh_from_db()
    ledger_services.post_journal(
        project=project, asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset, account_type=AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": 700_000},
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset,
                account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1"),
             "side": "credit", "amount": 700_000},
        ],
        idempotency_key="seed:sweeps", operation_type="deposit", operation_id="seed",
    )
    return {
        "org": org, "project": project, "network": network, "asset": asset,
        "wallet": wallet, "owner": owner, "approver": approver,
    }


def register(ctx, url: str = "https://tenant.example/sweep-destination"):
    return services.register_endpoint(
        project=ctx["project"], url=url, actor=ctx["owner"], dns_resolver=PUBLIC_DNS
    )


def make_sweep(ctx, key: str = "swp-1") -> Sweep:
    return services.create_sweep(
        wallet=ctx["wallet"], network=ctx["network"], asset=ctx["asset"],
        idempotency_key=key,
    )


def balance(ctx, account_type, ref="cust_1") -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=ctx["asset"],
        account_type=account_type, external_ref=ref,
    )
    return ledger_services.account_balance(account)


# -------------------------------------------------------- resolver matrix


def test_resolver_ssrf_and_format_matrix(ctx) -> None:
    network, asset = ctx["network"], ctx["asset"]

    def attempt(url: str, dns=PUBLIC_DNS, client=None):
        return resolver.resolve_destination(
            endpoint_url=url, network=network, asset=asset, request_id="t1",
            dns_resolver=dns, http_client=client or endpoint_client(DEST.encode()),
        )

    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("http://tenant.example/x")
    assert caught.value.stage == "ssrf"
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://tenant.example/x", dns=lambda host: ["10.0.0.5"])
    assert caught.value.stage == "ssrf"
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://169.254.169.254/latest/meta-data")
    assert caught.value.stage == "ssrf"
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://user:pass@tenant.example/x")
    assert caught.value.stage == "ssrf"
    # Redirects are never followed.
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://tenant.example/x", client=endpoint_client(b"", 302, {"location": "https://evil.example/"}))
    assert caught.value.stage == "redirect"
    # JSON is not a plain-text address.
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://tenant.example/x", client=endpoint_client(b'{"address": "' + DEST.encode() + b'"}'))
    assert caught.value.stage == "format"
    # Two tokens / commentary: rejected, never "picked".
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://tenant.example/x", client=endpoint_client((DEST + " " + DEST2).encode()))
    assert caught.value.stage == "format"
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://tenant.example/x", client=endpoint_client(b"A" * 600))
    assert caught.value.stage == "too_large"
    # An address valid for another network is a failure, not a sweep.
    with pytest.raises(resolver.ResolutionError) as caught:
        attempt("https://tenant.example/x", client=endpoint_client(b"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"))
    assert caught.value.stage == "wrong_network"
    # Happy path: trimmed single token, normalized for the network.
    result = attempt("https://tenant.example/x", client=endpoint_client(("  " + DEST + "\n").encode()))
    assert result.address == DEST
    assert result.normalized == DEST.lower()


def test_registration_validation_history_and_disable(ctx) -> None:
    with pytest.raises(resolver.ResolutionError):
        services.register_endpoint(
            project=ctx["project"], url="http://tenant.example/x", actor=ctx["owner"],
            dns_resolver=PUBLIC_DNS,
        )
    endpoint = register(ctx)
    assert SweepDestinationEndpoint.objects.filter(project=ctx["project"]).exists()
    register(ctx, url="https://tenant.example/v2")
    endpoint.refresh_from_db()
    assert endpoint.version == 2
    history = list(endpoint.history.all())
    assert [row.action for row in history] == ["registered", "updated"]
    assert history[0].new_url_hash != history[1].new_url_hash
    services.disable_endpoint(project=ctx["project"], actor=ctx["owner"])
    endpoint.refresh_from_db()
    assert endpoint.enabled is False


# -------------------------------------------------------------- sweep flow


def test_sweep_full_cycle_with_approval_and_snapshot(ctx) -> None:
    register(ctx)
    sweep = make_sweep(ctx)
    provider = FakeProvider(ctx["network"])
    kwargs = {"http_client": endpoint_client(DEST.encode()), "dns_resolver": PUBLIC_DNS}
    # Default withdrawal policy requires 1 approval.
    processed = services.process_sweep(sweep=sweep, factories=factories(provider), resolver_kwargs=kwargs)
    assert processed.status == Sweep.Status.AWAITING_APPROVAL
    snapshot = processed.destination_snapshot
    assert snapshot.destination_address == DEST
    # Snapshots are immutable.
    snapshot.destination_address = DEST2
    with pytest.raises(ValueError):
        snapshot.save()
    snapshot.refresh_from_db()
    assert snapshot.destination_address == DEST
    # Endpoint starts returning a DIFFERENT address: the approved
    # sweep must still use the snapshot (§7), never re-resolve.
    approved = services.record_sweep_approval(
        sweep=processed, approver=ctx["approver"], decision="approved"
    )
    assert approved.status == Sweep.Status.RESOLVED
    executed = services.process_sweep(
        sweep=approved, factories=factories(provider),
        resolver_kwargs={"http_client": endpoint_client(DEST2.encode()), "dns_resolver": PUBLIC_DNS},
    )
    assert executed.status == Sweep.Status.BROADCAST
    fresh_snapshot = ResolvedDestinationSnapshot.objects.get(sweep=executed)
    assert fresh_snapshot.destination_address == DEST
    assert int(executed.amount) == 700_000
    provider.receipt = {
        "status": "0x1", "blockNumber": hex(1999),
        "gasUsed": hex(21_000), "effectiveGasPrice": hex(1_000_000_000),
    }
    done = services.refresh_sweep(sweep=executed, factories=factories(provider))
    assert done.status == Sweep.Status.COMPLETED
    assert balance(ctx, AccountType.CUSTOMER_AVAILABLE) == 0
    assert ledger_services.trial_balance(ctx["project"], ctx["asset"]) == 0


def test_sweep_fail_closed_variants(ctx) -> None:
    provider = FakeProvider(ctx["network"])
    # No endpoint at all.
    sweep = make_sweep(ctx, "fc-1")
    out = services.process_sweep(sweep=sweep, factories=factories(provider))
    assert out.status == Sweep.Status.RESOLUTION_FAILED
    register(ctx)
    # Endpoint returns a blacklisted destination.
    BlacklistEntry.objects.create(
        scope="platform", network=ctx["network"], address=DEST,
        normalized_address=DEST.lower(), reason="test", created_by=ctx["owner"],
    )
    sweep = make_sweep(ctx, "fc-2")
    out = services.process_sweep(
        sweep=sweep, factories=factories(provider),
        resolver_kwargs={"http_client": endpoint_client(DEST.encode()), "dns_resolver": PUBLIC_DNS},
    )
    assert out.status == Sweep.Status.POLICY_DENIED
    BlacklistEntry.objects.all().delete()
    # Endpoint returns the wallet's OWN address (self-sweep).
    sweep = make_sweep(ctx, "fc-3")
    out = services.process_sweep(
        sweep=sweep, factories=factories(provider),
        resolver_kwargs={"http_client": endpoint_client(FROM.encode()), "dns_resolver": PUBLIC_DNS},
    )
    assert out.status == Sweep.Status.POLICY_DENIED
    # Endpoint unreachable.
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    sweep = make_sweep(ctx, "fc-4")
    out = services.process_sweep(
        sweep=sweep, factories=factories(provider),
        resolver_kwargs={
            "http_client": httpx.Client(transport=httpx.MockTransport(down)),
            "dns_resolver": PUBLIC_DNS,
        },
    )
    assert out.status == Sweep.Status.RESOLUTION_FAILED
    assert "transport" in out.status_reason


def test_sweep_below_threshold_and_policy(ctx) -> None:
    register(ctx)
    SweepPolicy.objects.create(
        project=ctx["project"], min_sweep_threshold=800_000, leave_behind=0
    )
    WithdrawalPolicy.objects.create(project=ctx["project"], asset=None, approvals_required=0)
    sweep = make_sweep(ctx)
    out = services.process_sweep(
        sweep=sweep, factories=factories(FakeProvider(ctx["network"])),
        resolver_kwargs={"http_client": endpoint_client(DEST.encode()), "dns_resolver": PUBLIC_DNS},
    )
    assert out.status == Sweep.Status.COMPLETED
    assert int(out.amount) == 0
    assert balance(ctx, AccountType.CUSTOMER_AVAILABLE) == 700_000  # untouched


def test_sweep_destination_never_from_request(ctx) -> None:
    import json

    from django.test import Client

    from tests.conftest import hmac_headers, make_api_key, make_org_project, register_user
    from waas.modules.projects.models import Project as ProjectModel

    client = Client()
    data = register_user(client, "sweep-api@example.com")
    token = data["access_token"]
    flow = make_org_project(client, token)
    project = ProjectModel.objects.get(id=flow["project"]["id"])
    wallet = Wallet.objects.create(project=project, label="api-wallet")
    key = make_api_key(client, token, flow["project"]["id"], scopes=["sweeps:write"])
    path = "/api/v1/sweeps"
    body = json.dumps({
        "wallet_id": str(wallet.id), "network": "ethereum",
        "asset_id": str(ctx["asset"].id), "destination_address": DEST,
    }).encode()
    headers = hmac_headers(key["secret"], key["key_id"], "POST", path, body)
    headers["HTTP_IDEMPOTENCY_KEY"] = "api-swp-1"
    response = client.post(path, data=body, content_type="application/json", **headers)
    assert response.status_code == 422
    assert "destination_not_allowed" in response.json()["detail"]
    assert Sweep.objects.count() == 0
    # Unknown fields are rejected too (closed schema).
    body2 = json.dumps({
        "wallet_id": str(wallet.id), "network": "ethereum",
        "asset_id": str(ctx["asset"].id), "surprise": "x",
    }).encode()
    headers2 = hmac_headers(key["secret"], key["key_id"], "POST", path, body2)
    headers2["HTTP_IDEMPOTENCY_KEY"] = "api-swp-2"
    response2 = client.post(path, data=body2, content_type="application/json", **headers2)
    assert response2.status_code == 422
