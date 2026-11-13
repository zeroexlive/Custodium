"""Phase 2 APIs: wallets, addresses (gated), resolve, balances."""
from __future__ import annotations

import json

import pytest
from django.core.management import call_command
from django.test import Client

from tests.conftest import auth_headers, hmac_headers, make_api_key, make_org_project, register_user
from waas.modules.assets.models import Asset
from waas.modules.ledger import services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet
from waas.modules.wallets.services import record_derived_address

pytestmark = pytest.mark.django_db


@pytest.fixture()
def seeded():
    call_command("seed_networks_assets")


def _make_wallet(client: Client, token: str, project_id: str, **extra) -> dict:
    resp = client.post(
        "/api/v1/wallets",
        data=json.dumps({"project_id": project_id, "label": "Main", **extra}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert resp.status_code == 201, resp.content
    return resp.json()


def test_dashboard_wallet_lifecycle(client: Client, seeded) -> None:
    data = register_user(client, "w1@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    project_id = ctx["project"]["id"]

    wallet = _make_wallet(client, token, project_id, external_customer_id="cust_8841")
    assert wallet["status"] == "provisioning"
    assert wallet["key_generation"] == {"ecdsa_key_ref": None, "ed25519_key_ref": None}

    listing = client.get(f"/api/v1/wallets?project_id={project_id}", **auth_headers(token))
    assert listing.status_code == 200
    # The project also holds its auto-created gas-station wallet
    # (William's workflow, 2026-11-14), hence total == 2.
    assert listing.json()["total"] == 2
    assert any(item["id"] == wallet["id"] for item in listing.json()["items"])

    # A provisioning wallet cannot be force-activated through the API.
    resp = client.patch(
        f"/api/v1/wallets/{wallet['id']}/status",
        data=json.dumps({"status": "active"}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert resp.status_code == 409
    resp = client.patch(
        f"/api/v1/wallets/{wallet['id']}/status",
        data=json.dumps({"status": "archived"}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


def test_wallet_create_idempotency_key_replay(client: Client, seeded) -> None:
    data = register_user(client, "w2@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    headers = {**auth_headers(token), "HTTP_IDEMPOTENCY_KEY": "create-wallet-1"}
    body = json.dumps({"project_id": ctx["project"]["id"], "label": "Once"})
    first = client.post("/api/v1/wallets", data=body, content_type="application/json", **headers)
    second = client.post("/api/v1/wallets", data=body, content_type="application/json", **headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    # Excluding the project's auto-created gas-station wallet.
    assert Wallet.objects.exclude(external_customer_id="gas-station").count() == 1


def test_machine_wallet_create_and_scope_enforcement(client: Client, seeded) -> None:
    data = register_user(client, "w3@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    project_id = ctx["project"]["id"]

    key = make_api_key(client, token, project_id, scopes=["wallets:write", "wallets:read"])
    path = "/api/v1/wallets"
    body = json.dumps({"label": "Machine wallet"}).encode()
    resp = client.post(path, data=body, content_type="application/json",
                       **hmac_headers(key["secret"], key["key_id"], "POST", path, body))
    assert resp.status_code == 201, resp.content
    assert resp.json()["project_id"] == project_id  # tenant context from the key

    readonly = make_api_key(client, token, project_id, scopes=["wallets:read"])
    resp = client.post(path, data=body, content_type="application/json",
                       **hmac_headers(readonly["secret"], readonly["key_id"], "POST", path, body))
    assert resp.status_code == 403


def test_wallet_tenant_isolation(client: Client, seeded) -> None:
    owner = register_user(client, "w4@example.com")
    ctx = make_org_project(client, owner["access_token"])
    wallet = _make_wallet(client, owner["access_token"], ctx["project"]["id"])

    stranger = register_user(client, "w5@example.com")
    make_org_project(client, stranger["access_token"], email_suffix="other")
    resp = client.get(f"/api/v1/wallets/{wallet['id']}", **auth_headers(stranger["access_token"]))
    assert resp.status_code == 404
    resp = client.get(
        f"/api/v1/wallets?project_id={ctx['project']['id']}",
        **auth_headers(stranger["access_token"]),
    )
    assert resp.status_code == 404


def test_address_creation_gated_and_recorded_addresses_visible(client: Client, seeded) -> None:
    data = register_user(client, "w6@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    wallet_data = _make_wallet(client, token, ctx["project"]["id"], external_customer_id="cust_9")
    project = Project.objects.get(id=ctx["project"]["id"])
    wallet = Wallet.objects.get(id=wallet_data["id"])

    resp = client.post(
        f"/api/v1/wallets/{wallet.id}/addresses",
        data=json.dumps({"network": "ethereum"}),
        content_type="application/json",
        **auth_headers(token),
    )
    assert resp.status_code == 409  # wallet not provisioned; nothing fabricated

    network = BlockchainNetwork.objects.get(slug="ethereum")
    record_derived_address(
        wallet=wallet, network=network,
        address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
        derivation_path="m/44'/60'/0'/0/0", derivation_index=0,
    )
    listing = client.get(f"/api/v1/wallets/{wallet.id}/addresses", **auth_headers(token))
    assert listing.status_code == 200
    assert listing.json()["items"][0]["address"] == "0xdAC17F958D2ee523a2206206994597C13D831ec7"

    resolved = client.post(
        "/api/v1/addresses/resolve",
        data=json.dumps({
            "project_id": str(project.id), "external_customer_id": "cust_9",
            "network": "ethereum",
        }),
        content_type="application/json",
        **auth_headers(token),
    )
    assert resolved.status_code == 200
    assert resolved.json()["wallet_id"] == str(wallet.id)

    unknown = client.post(
        "/api/v1/addresses/resolve",
        data=json.dumps({
            "project_id": str(project.id), "external_customer_id": "nobody",
            "network": "ethereum",
        }),
        content_type="application/json",
        **auth_headers(token),
    )
    assert unknown.status_code == 404


def test_balances_api_returns_exact_integer_strings(client: Client, seeded) -> None:
    data = register_user(client, "w7@example.com")
    token = data["access_token"]
    ctx = make_org_project(client, token)
    project = Project.objects.get(id=ctx["project"]["id"])
    usdt = Asset.objects.get(network__slug="ethereum", symbol="USDT")
    custody = services.get_or_create_account(
        project=project, asset=usdt, account_type=AccountType.CUSTODY_ONCHAIN
    )
    available = services.get_or_create_account(
        project=project, asset=usdt, account_type=AccountType.CUSTOMER_AVAILABLE,
        external_ref="cust_1",
    )
    services.post_journal(
        project=project, asset=usdt, entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": custody, "side": "debit", "amount": 100_000_000},
            {"account": available, "side": "credit", "amount": 100_000_000},
        ],
        idempotency_key="api-dep-1", operation_type="deposit", operation_id="api-dep-1",
    )
    resp = client.get(f"/api/v1/projects/{project.id}/balances", **auth_headers(token))
    assert resp.status_code == 200, resp.content
    block = resp.json()["items"][0]
    assert block["symbol"] == "USDT"
    assert block["available"] == "100000000"
    assert block["accounts"]["custody_onchain"] == "100000000"
    assert isinstance(block["available"], str)  # integer string, never a float
