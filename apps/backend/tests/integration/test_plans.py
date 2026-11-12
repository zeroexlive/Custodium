"""Phase 11 commercial layer: plan defaults, usage metering,
quota enforcement, invoicing with overage, team management, and
the audit export."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from tests.conftest import auth_headers, register_user
from waas.modules.organizations.models import Membership, Organization
from waas.modules.plans import services
from waas.modules.plans.models import Invoice, Plan
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db


@pytest.fixture()
def ctx():
    call_command("seed_plans")
    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Billing Org", slug="billing-org")
    owner = User.objects.create_user(email="bill-owner@example.com", password="x" * 12)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=owner
    )
    return {"org": org, "owner": owner, "project": project}


def test_default_plan_and_usage(ctx) -> None:
    assert services.get_plan(ctx["org"]).slug == "sandbox"
    Wallet.objects.create(project=ctx["project"], label="w1")
    snapshot = services.usage_snapshot(ctx["org"])
    assert snapshot["wallets"] == {"used": 1, "limit": 25}
    assert snapshot["withdrawals_this_period"]["included"] == 100


def test_quota_enforcement(ctx) -> None:
    plan = Plan.objects.get(slug="sandbox")
    plan.quotas = {**plan.quotas, "max_wallets": 1}
    plan.save(update_fields=["quotas"])
    Wallet.objects.create(project=ctx["project"], label="w1")
    with pytest.raises(services.QuotaExceeded):
        services.check_wallet_quota(ctx["project"])


def test_invoice_with_overage_is_idempotent(ctx) -> None:
    plan = Plan.objects.create(
        slug="metered", name="Metered", monthly_price_cents=10_000,
        quotas={
            "max_wallets": 25, "max_api_keys_per_project": 10,
            "included_withdrawals_per_month": 1, "withdrawal_overage_cents": 30,
        },
    )
    from waas.modules.plans.models import OrganizationSubscription

    OrganizationSubscription.objects.create(organization=ctx["org"], plan=plan)
    from waas.modules.assets.models import Asset
    from waas.modules.networks.models import BlockchainNetwork
    from waas.modules.operations.models import WithdrawalRequest

    network = BlockchainNetwork.objects.get(slug="ethereum")
    asset = Asset.objects.get(network=network, symbol="USDT")
    wallet = Wallet.objects.create(project=ctx["project"], label="metered")
    for index in range(3):
        WithdrawalRequest.objects.create(
            project=ctx["project"], wallet=wallet, network=network, asset=asset,
            destination_address="0x3535353535353535353535353535353535353535",
            amount=100, idempotency_key=f"inv-{index}",
            status=WithdrawalRequest.Status.COMPLETED,
        )
    invoice = services.generate_invoice(ctx["org"])
    assert invoice.total_cents == 10_000 + 2 * 30  # 3 used − 1 included = 2 over
    again = services.generate_invoice(ctx["org"])
    assert again.id == invoice.id
    assert Invoice.objects.filter(organization=ctx["org"]).count() == 1


def test_team_management_and_audit_export() -> None:
    client = Client()
    owner = register_user(client, "team-owner@example.com")
    invitee = register_user(client, "team-member@example.com")
    token = owner["access_token"]
    created = client.post(
        "/api/v1/organizations",
        data=json.dumps({"name": "Team Org"}),
        content_type="application/json",
        **auth_headers(token),
    )
    org_id = created.json()["id"]
    # The invitee is not a member yet: no existence leak.
    assert client.get(
        f"/api/v1/organizations/{org_id}/members", **auth_headers(invitee["access_token"])
    ).status_code == 404
    added = client.post(
        f"/api/v1/organizations/{org_id}/members",
        data=json.dumps({"email": "team-member@example.com", "role": "developer"}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert added.status_code == 201, added.content[:200]
    membership_id = added.json()["membership_id"]
    changed = client.patch(
        f"/api/v1/organizations/{org_id}/members/{membership_id}",
        data=json.dumps({"role": "finance_operator"}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "finance_operator"
    # The sole owner cannot be removed.
    owner_membership = Membership.objects.get(
        organization_id=org_id, role=Membership.Role.OWNER
    )
    blocked = client.delete(
        f"/api/v1/organizations/{org_id}/members/{owner_membership.id}",
        **auth_headers(token),
    )
    assert blocked.status_code == 422
    # Audit export is a real CSV download.
    export = client.get("/api/v1/audit-logs/export", **auth_headers(token))
    assert export.status_code == 200
    assert export["Content-Type"] == "text/csv"
    assert b"organization.member_added" in export.content
