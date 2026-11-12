"""Manual blacklist API: roles, scoping, normalisation, soft-disable, checks.

The blacklist is a manual operations tool — not an AML/KYT system.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from tests.conftest import auth_headers, hmac_headers, make_api_key, make_org_project, register_user
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.identity.models import User
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Membership, Organization

pytestmark = pytest.mark.django_db

CHECKSUM_ADDR = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
LOWER_ADDR = "0xdac17f958d2ee523a2206206994597c13d831ec7"


@pytest.fixture()
def seeded():
    call_command("seed_networks_assets")


def _create_entry(client: Client, token: str, **payload) -> object:
    return client.post(
        "/api/v1/blacklist/entries",
        data=json.dumps(payload),
        content_type="application/json",
        **auth_headers(token),
    )


def test_tenant_entry_lifecycle_and_normalised_matching(client: Client, seeded) -> None:
    data = register_user(client, "b1@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    org_id = ctx["organization"]["id"]

    resp = _create_entry(
        client, token, scope="tenant", organization_id=org_id, network="ethereum",
        address=CHECKSUM_ADDR, reason="Confirmed theft destination (manual review)",
    )
    assert resp.status_code == 201, resp.content
    entry = resp.json()
    assert entry["normalized_address"] == LOWER_ADDR

    # Matching is case-insensitive for EVM via the normalised form.
    check = client.get(
        f"/api/v1/blacklist/check?address={LOWER_ADDR}&network=ethereum&organization_id={org_id}",
        **auth_headers(token),
    )
    assert check.status_code == 200
    assert check.json()["blacklisted"] is True
    assert check.json()["matched_scopes"] == ["tenant"]
    assert "reason" not in check.json()  # checks never leak notes

    # Disable (soft) -> no longer effective, still listed for audit.
    disable = client.post(
        f"/api/v1/blacklist/entries/{entry['id']}/disable",
        data="{}", content_type="application/json", **auth_headers(token),
    )
    assert disable.status_code == 200
    assert disable.json()["active"] is False
    check = client.get(
        f"/api/v1/blacklist/check?address={LOWER_ADDR}&network=ethereum&organization_id={org_id}",
        **auth_headers(token),
    )
    assert check.json()["blacklisted"] is False
    listing = client.get(f"/api/v1/blacklist/entries?organization_id={org_id}", **auth_headers(token))
    assert listing.json()["total"] == 1


def test_tenant_entries_do_not_leak_across_organizations(client: Client, seeded) -> None:
    owner = register_user(client, "b2@example.com")
    ctx = make_org_project(client, owner["access_token"])
    _create_entry(
        client, owner["access_token"], scope="tenant",
        organization_id=ctx["organization"]["id"], network="ethereum",
        address=CHECKSUM_ADDR, reason="tenant A decision",
    )
    other = register_user(client, "b3@example.com")
    other_ctx = make_org_project(client, other["access_token"], email_suffix="other")
    check = client.get(
        f"/api/v1/blacklist/check?address={LOWER_ADDR}&network=ethereum"
        f"&organization_id={other_ctx['organization']['id']}",
        **auth_headers(other["access_token"]),
    )
    assert check.json()["blacklisted"] is False


def test_platform_entries_require_staff_and_apply_globally(client: Client, seeded) -> None:
    data = register_user(client, "b4@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    resp = _create_entry(
        client, token, scope="platform", network="ethereum",
        address=CHECKSUM_ADDR, reason="platform decision",
    )
    assert resp.status_code == 403  # not staff

    staff = User.objects.create_user(email="ops@example.com", password="x", is_staff=True)
    from waas.modules.identity.models import DashboardToken

    _, staff_token = DashboardToken.issue(staff)
    resp = _create_entry(
        client, staff_token, scope="platform", network="ethereum",
        address=CHECKSUM_ADDR, reason="Sanctioned by platform ops (manual)",
    )
    assert resp.status_code == 201, resp.content

    check = client.get(
        f"/api/v1/blacklist/check?address={LOWER_ADDR}&network=ethereum"
        f"&organization_id={ctx['organization']['id']}",
        **auth_headers(token),
    )
    assert check.json()["blacklisted"] is True
    assert check.json()["matched_scopes"] == ["platform"]


def test_invalid_address_and_missing_reason_rejected(client: Client, seeded) -> None:
    data = register_user(client, "b5@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    org_id = ctx["organization"]["id"]
    resp = _create_entry(
        client, token, scope="tenant", organization_id=org_id, network="ethereum",
        address="0xnotanaddress", reason="bad input",
    )
    assert resp.status_code == 422
    resp = _create_entry(
        client, token, scope="tenant", organization_id=org_id, network="ethereum",
        address=CHECKSUM_ADDR, reason="  ",
    )
    assert resp.status_code == 422
    check = client.get(
        f"/api/v1/blacklist/check?address=garbage&network=ethereum&organization_id={org_id}",
        **auth_headers(token),
    )
    assert check.status_code == 422  # unparseable is an error, never a silent miss


def test_non_admin_member_cannot_create(client: Client, seeded) -> None:
    owner = register_user(client, "b6@example.com")
    ctx = make_org_project(client, owner["access_token"])
    viewer_data = register_user(client, "b7@example.com")
    viewer = User.objects.get(email="b7@example.com")
    org = Organization.objects.get(id=ctx["organization"]["id"])
    Membership.objects.create(user=viewer, organization=org, role=Membership.Role.VIEWER)
    resp = _create_entry(
        client, viewer_data["access_token"], scope="tenant", organization_id=str(org.id),
        network="ethereum", address=CHECKSUM_ADDR, reason="viewer attempt",
    )
    assert resp.status_code == 403


def test_expired_entries_do_not_block_and_machine_check(client: Client, seeded) -> None:
    owner = register_user(client, "b8@example.com")
    token = owner["access_token"]
    ctx = make_org_project(client, token)
    network = BlockchainNetwork.objects.get(slug="ethereum")
    org = Organization.objects.get(id=ctx["organization"]["id"])
    creator = User.objects.get(email="b8@example.com")
    BlacklistEntry.objects.create(
        scope="tenant", organization=org, network=network, address=CHECKSUM_ADDR,
        normalized_address=LOWER_ADDR, reason="expired entry", created_by=creator,
        expires_at=timezone.now() - timedelta(days=1),
    )
    check = client.get(
        f"/api/v1/blacklist/check?address={LOWER_ADDR}&network=ethereum&organization_id={org.id}",
        **auth_headers(token),
    )
    assert check.json()["blacklisted"] is False

    # Machine check via HMAC uses the key's own tenant context.
    _create_entry(
        client, token, scope="tenant", organization_id=str(org.id), network="ethereum",
        address=CHECKSUM_ADDR, reason="active entry",
    )
    key = make_api_key(client, token, ctx["project"]["id"], scopes=["read"])
    path = f"/api/v1/blacklist/check?address={LOWER_ADDR}&network=ethereum"
    resp = client.get(path, **hmac_headers(key["secret"], key["key_id"], "GET", path))
    assert resp.status_code == 200, resp.content
    assert resp.json()["blacklisted"] is True
