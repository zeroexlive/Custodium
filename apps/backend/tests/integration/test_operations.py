"""Phase 9 financial operations: policy evaluation, maker-checker
approvals, dispatch through a chain pipeline with service-fee
accounting, reconciliation halts, refunds, and exports.
"""

from __future__ import annotations

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
from waas.modules.operations import dispatch, services
from waas.modules.operations.models import (
    ReconciliationHalt,
    WithdrawalPolicy,
    WithdrawalRequest,
)
from waas.modules.organizations.models import Membership, Organization
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db

_EC_KEY = ec.derive_private_key(int.from_bytes(b"\x11" * 32, "big"), ec.SECP256K1())
_NUMBERS = _EC_KEY.public_key().public_numbers()
TEST_PUBKEY = _NUMBERS.x.to_bytes(32, "big") + _NUMBERS.y.to_bytes(32, "big")
FROM = evm_keys.address_from_public_key(TEST_PUBKEY)
DEST = "0x3535353535353535353535353535353535353535"


class TestSigner:
    """TEST-ONLY signer double. Never production."""

    def wallet_public_key(self, wallet) -> bytes:
        return TEST_PUBKEY

    def sign_digest(self, wallet, digest: bytes):
        der = _EC_KEY.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return utils.decode_dss_signature(der)


class FakeProvider:
    """In-memory provider double with the EvmProvider surface
    (mirrors the Phase 4 pipeline tests)."""

    def __init__(self, network) -> None:
        from waas.modules.evm.chains import EvmChain

        self.chain = EvmChain(network=network, endpoints=("memory://",))
        self.sent: list[bytes] = []
        self.receipt: dict | None = None
        self.current_block = 2000

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
        return "0x" + (b"\xab" * 32).hex()

    def get_receipt(self, tx_hash: str):
        return self.receipt

    def block_number(self) -> int:
        return self.current_block


def factories(provider) -> dispatch.Factories:
    return dispatch.Factories(
        provider=lambda network: provider,
        ecdsa_signer=lambda: TestSigner(),
        ed25519_signer=lambda: TestSigner(),
    )


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Ops Org", slug="ops-org")
    owner = User.objects.create_user(email="owner@example.com", password="x" * 12)
    approver = User.objects.create_user(email="appr@example.com", password="x" * 12)
    viewer = User.objects.create_user(email="view@example.com", password="x" * 12)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    Membership.objects.create(
        organization=org, user=approver, role=Membership.Role.WITHDRAWAL_APPROVER
    )
    Membership.objects.create(organization=org, user=viewer, role=Membership.Role.VIEWER)
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=owner
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    asset = Asset.objects.get(network=network, symbol="USDT")
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    from waas.modules.wallets import services as wallet_services

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
             "side": "debit", "amount": 1_000_000},
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset,
                account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1"),
             "side": "credit", "amount": 1_000_000},
        ],
        idempotency_key="seed:ops", operation_type="deposit", operation_id="seed",
    )
    return {
        "org": org, "project": project, "network": network, "asset": asset,
        "wallet": wallet, "owner": owner, "approver": approver, "viewer": viewer,
    }


def balance(ctx, account_type, ref="cust_1") -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=ctx["asset"],
        account_type=account_type, external_ref=ref,
    )
    return ledger_services.account_balance(account)


def create(ctx, **overrides):
    params = {
        "wallet": ctx["wallet"], "network": ctx["network"], "asset": ctx["asset"],
        "destination_address": DEST, "amount": 100_000,
        "idempotency_key": "req-1",
    }
    params.update(overrides)
    return services.create_withdrawal_request(**params)


def test_default_policy_needs_one_approval(ctx) -> None:
    request = create(ctx)
    assert request.status == WithdrawalRequest.Status.PENDING_POLICY
    assert request.approvals_required == 1
    # Maker-checker does not apply to API requests, but role does:
    with pytest.raises(services.OperationsError):
        services.record_approval(request=request, approver=ctx["viewer"], decision="approved")
    updated = services.record_approval(
        request=request, approver=ctx["approver"], decision="approved"
    )
    assert updated.status == WithdrawalRequest.Status.APPROVED
    # Duplicate decision by the same user is refused.
    request2 = create(ctx, idempotency_key="req-2")
    services.record_approval(request=request2, approver=ctx["approver"], decision="rejected")
    assert request2.status == WithdrawalRequest.Status.REJECTED


def test_maker_checker_blocks_self_approval(ctx) -> None:
    request = create(
        ctx, requested_by_type="dashboard", requested_by_id=str(ctx["owner"].id)
    )
    with pytest.raises(services.OperationsError):
        services.record_approval(request=request, approver=ctx["owner"], decision="approved")
    updated = services.record_approval(
        request=request, approver=ctx["approver"], decision="approved"
    )
    assert updated.status == WithdrawalRequest.Status.APPROVED


def test_policy_limits_and_auto_approve(ctx) -> None:
    WithdrawalPolicy.objects.create(
        project=ctx["project"], asset=None, max_single_amount=50_000,
        daily_limit=80_000, approvals_required=2, auto_approve_below=10_000,
        service_fee_flat=0,
    )
    too_big = create(ctx, amount=60_000, idempotency_key="p-1")
    assert too_big.status == WithdrawalRequest.Status.REJECTED
    assert "single" in too_big.status_reason
    small = create(ctx, amount=5_000, idempotency_key="p-2")
    assert small.status == WithdrawalRequest.Status.APPROVED  # auto-approved
    mid = create(ctx, amount=40_000, idempotency_key="p-3")
    # Counted so far: 5_000; +40_000 = 45_000 <= 80_000 OK, 2 approvals.
    assert mid.status == WithdrawalRequest.Status.PENDING_POLICY
    assert mid.approvals_required == 2
    over_daily = create(ctx, amount=45_000, idempotency_key="p-4")
    # 45_000 counted + 45_000 = 90_000 > 80_000 daily limit.
    assert over_daily.status == WithdrawalRequest.Status.REJECTED
    assert "daily" in over_daily.status_reason


def test_create_guards_idempotency_blacklist_halt(ctx) -> None:
    first = create(ctx)
    again = create(ctx)
    assert again.id == first.id
    BlacklistEntry.objects.create(
        scope="platform", network=ctx["network"], address=DEST,
        normalized_address=DEST.lower(), reason="test", created_by=ctx["owner"],
    )
    with pytest.raises(services.OperationsError):
        create(ctx, idempotency_key="req-bl")
    BlacklistEntry.objects.all().delete()
    ReconciliationHalt.objects.create(network=ctx["network"], active=True, reason="test")
    with pytest.raises(services.OperationsError):
        create(ctx, idempotency_key="req-halt")


def _approved_with_fee(ctx) -> WithdrawalRequest:
    WithdrawalPolicy.objects.create(
        project=ctx["project"], asset=None, approvals_required=0,
        service_fee_flat=1_000,
    )
    return create(ctx, idempotency_key="fee-1")


def test_dispatch_fee_and_completion_with_actual_fee(ctx) -> None:
    request = _approved_with_fee(ctx)
    assert request.status == WithdrawalRequest.Status.APPROVED
    provider = FakeProvider(ctx["network"])
    dispatched = services.dispatch_withdrawal(request=request, factories=factories(provider))
    assert dispatched.status == WithdrawalRequest.Status.BROADCAST, dispatched.status_reason
    assert dispatched.chain_family == "evm"
    # Service fee moved to platform fees at dispatch; the payout
    # amount sits in the withdrawal reservation.
    assert balance(ctx, AccountType.PLATFORM_FEES_PAYABLE, ref="") == 1_000
    assert balance(ctx, AccountType.CUSTOMER_AVAILABLE) == 899_000
    assert balance(ctx, AccountType.WITHDRAWAL_RESERVED) == 100_000
    ctx["network"].confirmations_required = 1
    ctx["network"].save(update_fields=["confirmations_required"])
    provider.receipt = {
        "status": "0x1", "blockNumber": hex(1990),
        "gasUsed": hex(21_000), "effectiveGasPrice": hex(2_000_000_000),
    }
    refreshed = services.refresh_withdrawal(request=dispatched, factories=factories(provider))
    assert refreshed.status == WithdrawalRequest.Status.COMPLETED
    assert int(refreshed.actual_fee) == 21_000 * 2_000_000_000
    assert refreshed.fee_asset.symbol == "ETH"
    assert balance(ctx, AccountType.CUSTOMER_AVAILABLE) == 899_000
    assert ledger_services.trial_balance(ctx["project"], ctx["asset"]) == 0


def test_failed_dispatch_reverses_service_fee(ctx) -> None:
    request = _approved_with_fee(ctx)
    # Default factories use the fail-closed signer: dispatch fails
    # honestly at signing and the fee must not survive.
    dispatched = services.dispatch_withdrawal(request=request)
    assert dispatched.status == WithdrawalRequest.Status.FAILED
    assert balance(ctx, AccountType.PLATFORM_FEES_PAYABLE, ref="") == 0
    assert balance(ctx, AccountType.CUSTOMER_AVAILABLE) == 1_000_000


def test_refund_playbook(ctx) -> None:
    request = _approved_with_fee(ctx)
    provider = FakeProvider(ctx["network"])
    ctx["network"].confirmations_required = 1
    ctx["network"].save(update_fields=["confirmations_required"])
    services.dispatch_withdrawal(request=request, factories=factories(provider))
    provider.receipt = {
        "status": "0x1", "blockNumber": hex(1999),
        "gasUsed": hex(21_000), "effectiveGasPrice": hex(1_000_000_000),
    }
    refreshed = services.refresh_withdrawal(request=request, factories=factories(provider))
    assert refreshed.status == WithdrawalRequest.Status.COMPLETED
    refunded = services.record_refund(
        request=refreshed, amount=40_000, actor=ctx["owner"], reason="destination returned funds"
    )
    assert int(refunded.refunded_amount) == 40_000
    assert balance(ctx, AccountType.CUSTOMER_AVAILABLE) == 899_000 + 40_000
    with pytest.raises(services.OperationsError):
        services.record_refund(
            request=refunded, amount=70_000, actor=ctx["owner"], reason="too much"
        )


def test_reconciliation_halt_cycle(ctx) -> None:
    report_bad = {
        "assets": [
            {"asset": "USDT", "expected_custody": 5, "ledger_custody": 6, "balanced": False}
        ]
    }
    assert services.apply_reconciliation_report(network=ctx["network"], report=report_bad)
    with pytest.raises(services.OperationsError):
        create(ctx, idempotency_key="halt-1")
    report_ok = {"assets": [{"asset": "USDT", "balanced": True}]}
    assert not services.apply_reconciliation_report(network=ctx["network"], report=report_ok)
    create(ctx, idempotency_key="halt-2")  # works again


def test_journal_export(ctx) -> None:
    content = services.export_journal_csv(project=ctx["project"])
    assert "deposit_credit" in content
    assert "1" in content and "cust_1" in content


# ------------------------------------------------------------ API surface


def _dashboard_client(user):
    from django.test import Client

    client = Client()
    token = user.issue_token() if hasattr(user, "issue_token") else None
    return client, token


def test_api_machine_create_and_dashboard_approve(ctx) -> None:
    import json

    from django.test import Client

    from tests.conftest import auth_headers, hmac_headers, make_api_key, make_org_project, register_user
    from waas.modules.projects.models import Project as ProjectModel

    client = Client()
    owner_data = register_user(client, "api-owner@example.com")
    token = owner_data["access_token"]
    flow = make_org_project(client, token)
    project = ProjectModel.objects.get(id=flow["project"]["id"])
    wallet = Wallet.objects.create(project=project, label="api-wallet")
    key = make_api_key(
        client, token, flow["project"]["id"],
        scopes=["withdrawals:write", "withdrawals:read"],
    )
    path = "/api/v1/withdrawals"
    body = json.dumps({
        "wallet_id": str(wallet.id),
        "network": "ethereum",
        "asset_id": str(ctx["asset"].id),
        "destination_address": DEST,
        "amount": "25000",
    }).encode()

    missing = client.post(
        path, data=body, content_type="application/json",
        **hmac_headers(key["secret"], key["key_id"], "POST", path, body),
    )
    assert missing.status_code == 422  # Idempotency-Key header required

    headers = hmac_headers(key["secret"], key["key_id"], "POST", path, body)
    headers["HTTP_IDEMPOTENCY_KEY"] = "api-req-1"
    response = client.post(path, data=body, content_type="application/json", **headers)
    assert response.status_code == 201, response.content[:200]
    payload = response.json()
    assert payload["status"] == "pending_policy"

    # The API-key requester is not a dashboard user, so the owner
    # may approve (maker-checker only binds dashboard requesters).
    decided = client.post(
        f"/api/v1/withdrawals/{payload['id']}/approve",
        data=json.dumps({"note": "ok"}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert decided.status_code == 200, decided.content[:200]
    assert decided.json()["status"] == "approved"
