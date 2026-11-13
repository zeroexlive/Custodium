"""Workflow-gap closures (2026-11-13): deposit minimums with
accumulation, withdrawal minimums, the gas-station top-up
address, and static (manual) sweep destinations.

Deposit tests drive the shared confirmation pass directly with
observed-deposit rows (the scanner families all funnel into it);
scanner-level detection is covered by the family test suites.
"""

from __future__ import annotations

import pytest
from django.test import Client

from tests.conftest import auth_headers
from waas.modules.assets.models import Asset
from waas.modules.gasstation.models import GasStation
from waas.modules.identity.models import DashboardToken, User
from waas.modules.indexing import services as indexing_services
from waas.modules.indexing.models import DepositPolicy, ObservedDeposit
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import services as ops_services
from waas.modules.operations.models import WithdrawalPolicy
from waas.modules.organizations.models import Membership, Organization
from waas.modules.projects.models import Project
from waas.modules.sweeps import services as sweep_services
from waas.modules.sweeps.models import Sweep, SweepPolicy
from waas.modules.wallets import services as wallet_services
from waas.modules.wallets.models import Wallet

FROM = "0x9d8A62f656a8d1615C1294fd71e9CFb3E4855A4F"
DEST = "0x1111111111111111111111111111111111111111"
WALLET_ADDR = "0x3333333333333333333333333333333333333333"


@pytest.fixture()
def ctx(db):
    from django.core.management import call_command

    call_command("seed_networks_assets")
    org = Organization.objects.create(name="Acme", slug="acme")
    owner = User.objects.create_user(email="wf-owner@example.com", password="x")
    project = Project.objects.create(
        organization=org, name="Live", environment=Project.Environment.SANDBOX,
        created_by=owner,
    )
    Membership.objects.create(
        organization=org, user=owner, role=Membership.Role.OWNER
    )
    viewer = User.objects.create_user(email="wf-viewer@example.com", password="x")
    Membership.objects.create(
        organization=org, user=viewer, role=Membership.Role.VIEWER
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    asset = Asset.objects.get(network=network, symbol="USDT")
    wallet = Wallet.objects.create(
        project=project, label="ops", external_customer_id="cust_1"
    )
    address = wallet_services.record_derived_address(
        wallet=wallet, network=network, address=WALLET_ADDR
    )
    _row, owner_token = DashboardToken.issue(owner)
    _row, viewer_token = DashboardToken.issue(viewer)
    return {
        "org": org, "project": project, "owner": owner, "viewer": viewer,
        "owner_token": owner_token, "viewer_token": viewer_token,
        "network": network, "asset": asset, "wallet": wallet,
        "address": address,
    }


def _deposit(ctx, amount: int, block: int, tx: str) -> ObservedDeposit:
    return ObservedDeposit.objects.create(
        network=ctx["network"], address=ctx["address"], wallet=ctx["wallet"],
        asset=ctx["asset"], tx_hash=tx, occurrence=0, from_address=FROM,
        amount=amount, block_number=block, block_hash="0x" + "ab" * 32,
    )


def _available(ctx) -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=ctx["asset"],
        account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1",
    )
    return ledger_services.account_balance(account)


@pytest.mark.django_db
class TestDepositMinimum:
    def test_below_minimum_holds_then_accumulates(self, ctx):
        DepositPolicy.objects.create(
            project=ctx["project"], asset=ctx["asset"], min_amount=100
        )
        first = _deposit(ctx, 60, 1, "0x" + "01" * 32)
        indexing_services.run_confirmation_pass(network=ctx["network"], head=500)
        first.refresh_from_db()
        assert first.status == ObservedDeposit.Status.PENDING
        assert first.held is True
        assert "below minimum" in first.hold_reason
        assert _available(ctx) == 0

        second = _deposit(ctx, 50, 2, "0x" + "02" * 32)
        indexing_services.run_confirmation_pass(network=ctx["network"], head=500)
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.status == ObservedDeposit.Status.CREDITED
        assert second.status == ObservedDeposit.Status.CREDITED
        assert _available(ctx) == 110

    def test_above_minimum_credits_and_releases_pool(self, ctx):
        DepositPolicy.objects.create(
            project=ctx["project"], asset=ctx["asset"], min_amount=100
        )
        small = _deposit(ctx, 30, 1, "0x" + "03" * 32)
        indexing_services.run_confirmation_pass(network=ctx["network"], head=500)
        big = _deposit(ctx, 500, 2, "0x" + "04" * 32)
        indexing_services.run_confirmation_pass(network=ctx["network"], head=500)
        small.refresh_from_db()
        big.refresh_from_db()
        assert big.status == ObservedDeposit.Status.CREDITED
        # The pool (30) plus the credited deposit released together
        # once the group total passed the minimum in this pass —
        # pool alone was 30 < 100, and stays held until a group
        # reaches it; here the group total is 530 >= 100 but the
        # pool-release rule credits the pool only when pool +
        # matured >= minimum at pass time, which holds.
        assert small.status == ObservedDeposit.Status.CREDITED
        assert _available(ctx) == 530

    def test_no_policy_credits_normally(self, ctx):
        tiny = _deposit(ctx, 1, 1, "0x" + "05" * 32)
        indexing_services.run_confirmation_pass(network=ctx["network"], head=500)
        tiny.refresh_from_db()
        assert tiny.status == ObservedDeposit.Status.CREDITED
        assert _available(ctx) == 1

    def test_policy_api(self, client: Client, ctx):
        url = "/api/v1/deposit-policies"
        put = client.put(
            url,
            data={
                "project_id": str(ctx["project"].id),
                "asset_id": str(ctx["asset"].id),
                "min_amount": "250",
            },
            content_type="application/json",
            **auth_headers(ctx["owner_token"]),
        )
        assert put.status_code == 200, put.content
        assert put.json()["min_amount"] == "250"
        forbidden = client.put(
            url,
            data={
                "project_id": str(ctx["project"].id),
                "asset_id": str(ctx["asset"].id),
                "min_amount": "1",
            },
            content_type="application/json",
            **auth_headers(ctx["viewer_token"]),
        )
        assert forbidden.status_code == 403
        listing = client.get(
            f"{url}?project_id={ctx['project'].id}",
            **auth_headers(ctx["viewer_token"]),
        )
        assert listing.status_code == 200 and listing.json()[0]["min_amount"] == "250"


@pytest.mark.django_db
class TestWithdrawalMinimum:
    def test_minimum_enforced_and_api_roundtrip(self, client: Client, ctx):
        url = f"/api/v1/projects/{ctx['project'].id}/withdrawal-policy"
        put = client.put(
            url,
            data={
                "min_single_amount": "500", "max_single_amount": "10000",
                "approvals_required": 1, "auto_approve_below": "0",
                "service_fee_flat": "0",
            },
            content_type="application/json",
            **auth_headers(ctx["owner_token"]),
        )
        assert put.status_code == 200, put.content
        assert put.json()["min_single_amount"] == "500"

        # Fund the wallet scope so only the policy can stop it.
        native = Asset.objects.get(network=ctx["network"], token_standard="native")
        _ = native  # policy applies per project default (asset NULL)
        policy = WithdrawalPolicy.objects.get(project=ctx["project"], asset__isnull=True)
        assert int(policy.min_single_amount) == 500

        request_obj = ops_services.create_withdrawal_request(
            wallet=ctx["wallet"], network=ctx["network"], asset=ctx["asset"],
            destination_address=DEST, amount=100,
            external_reference="wd-min", idempotency_key="wd-min",
            requested_by_type="api_key", requested_by_id="test",
        )
        assert request_obj.status == "rejected"
        assert "minimum" in request_obj.status_reason

        ok = ops_services.create_withdrawal_request(
            wallet=ctx["wallet"], network=ctx["network"], asset=ctx["asset"],
            destination_address=DEST, amount=600,
            external_reference="wd-ok", idempotency_key="wd-ok",
            requested_by_type="api_key", requested_by_id="test",
        )
        assert ok.status != "rejected"


@pytest.mark.django_db
class TestGasStationTopUpAddress:
    def test_station_response_includes_top_up_address(self, client: Client, ctx):
        funding = Wallet.objects.create(project=ctx["project"], label="gas")
        wallet_services.record_derived_address(
            wallet=funding, network=ctx["network"], address=DEST
        )
        GasStation.objects.create(
            project=ctx["project"], network=ctx["network"],
            funding_wallet=funding, min_native_balance=10**15,
            topup_amount=10**16, max_topups_per_day=3,
        )
        resp = client.get(
            f"/api/v1/gas-stations?project_id={ctx['project'].id}",
            **auth_headers(ctx["owner_token"]),
        )
        assert resp.status_code == 200, resp.content
        rows = resp.json()["items"] if isinstance(resp.json(), dict) else resp.json()
        assert rows[0]["top_up_address"] == DEST
        assert rows[0]["network"] == "ethereum"


@pytest.mark.django_db
class TestStaticSweepDestinations:
    def _sweep(self, ctx) -> Sweep:
        return sweep_services.create_sweep(
            wallet=ctx["wallet"], network=ctx["network"], asset=ctx["asset"],
            idempotency_key="sw-static-1",
        )

    def test_static_mode_resolves_from_registered_address(self, ctx):
        # Fund the wallet scope so the sweep proceeds past amount
        # discovery to awaiting-approval (an empty wallet completes
        # as "nothing to sweep" right after resolution).
        ledger_services.post_journal(
            project=ctx["project"], asset=ctx["asset"],
            entry_type="deposit_credit",
            lines=[
                {"account": ledger_services.get_or_create_account(
                    project=ctx["project"], asset=ctx["asset"],
                    account_type=AccountType.CUSTODY_ONCHAIN),
                 "side": "debit", "amount": 1_000_000},
                {"account": ledger_services.get_or_create_account(
                    project=ctx["project"], asset=ctx["asset"],
                    account_type=AccountType.CUSTOMER_AVAILABLE,
                    external_ref="cust_1"),
                 "side": "credit", "amount": 1_000_000},
            ],
            idempotency_key="seed:fund-static",
            operation_type="deposit", operation_id="seed",
        )
        SweepPolicy.objects.create(
            project=ctx["project"], destination_mode=SweepPolicy.DestinationMode.STATIC
        )
        sweep_services.set_static_destination(
            project=ctx["project"], network=ctx["network"], address=DEST,
            actor=ctx["owner"],
        )
        sweep = self._sweep(ctx)
        processed = sweep_services.process_sweep(sweep=sweep)
        assert processed.status == Sweep.Status.AWAITING_APPROVAL
        snapshot = processed.destination_snapshot
        assert snapshot.source == "static"
        assert snapshot.destination_address == DEST

    def test_static_mode_without_destination_fails_closed(self, ctx):
        SweepPolicy.objects.create(
            project=ctx["project"], destination_mode=SweepPolicy.DestinationMode.STATIC
        )
        sweep = self._sweep(ctx)
        processed = sweep_services.process_sweep(sweep=sweep)
        assert processed.status == Sweep.Status.RESOLUTION_FAILED
        assert not hasattr(processed, "destination_snapshot") or (
            processed.destination_snapshot is None
        )

    def test_api_and_validation(self, client: Client, ctx):
        put_policy = client.put(
            "/api/v1/sweep-policy",
            data={
                "project_id": str(ctx["project"].id),
                "destination_mode": "static",
                "min_sweep_threshold": "0", "leave_behind": "0",
                "enabled": True,
            },
            content_type="application/json",
            **auth_headers(ctx["owner_token"]),
        )
        assert put_policy.status_code == 200, put_policy.content
        assert put_policy.json()["destination_mode"] == "static"

        bad = client.put(
            "/api/v1/sweep-destinations",
            data={
                "project_id": str(ctx["project"].id), "network": "ethereum",
                "address": "not-an-address",
            },
            content_type="application/json",
            **auth_headers(ctx["owner_token"]),
        )
        assert bad.status_code == 422
        good = client.put(
            "/api/v1/sweep-destinations",
            data={
                "project_id": str(ctx["project"].id), "network": "ethereum",
                "address": DEST, "label": "hot wallet",
            },
            content_type="application/json",
            **auth_headers(ctx["owner_token"]),
        )
        assert good.status_code == 200, good.content
        assert good.json()["address"] == DEST
        forbidden = client.put(
            "/api/v1/sweep-destinations",
            data={
                "project_id": str(ctx["project"].id), "network": "ethereum",
                "address": DEST,
            },
            content_type="application/json",
            **auth_headers(ctx["viewer_token"]),
        )
        assert forbidden.status_code == 403
