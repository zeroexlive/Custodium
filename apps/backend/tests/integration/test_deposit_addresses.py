"""Deposit addresses by customer UID (William's workflow, 2026-11-14):

- API mode: the customer's server sends a UID + chain and receives
  the user's deposit address (find-or-create the UID's wallet;
  unprovisioned wallets get an honest 409, never a fabricated
  address).
- Manual mode: the same endpoint with a dashboard session, where
  the customer typed the UID themselves.
- Search: by address -> the owning UID; by UID -> all addresses,
  each with status and a deposit summary for troubleshooting.
- Creating a wallet guarantees the project's gas sponsor exists.
"""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command
from django.test import Client

from tests.conftest import (
    auth_headers,
    hmac_headers,
    make_api_key,
    register_user,
)
from waas.modules.assets.models import Asset
from waas.modules.indexing.models import ObservedDeposit
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Address, Wallet

GENERATOR_HEX = (
    "0479be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
    "483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8"
)
ED25519_HEX = "11" * 32
EVM_ADDR = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
SOLANA_ADDR = "29d2S7vB453rNYFdR5Ycwt7y9haRT5fwVwL9zTmBhfV2"


@pytest.fixture
def ctx(db) -> dict:
    call_command("seed_networks_assets")
    client = Client()
    user = register_user(client, "owner@example.com")
    org = client.post(
        "/api/v1/organizations",
        data='{"name": "Acme"}',
        content_type="application/json",
        **auth_headers(user["token"]),
    ).json()
    project = client.post(
        "/api/v1/projects",
        data=json.dumps(
            {"organization_id": org["id"], "name": "Main", "environment": "sandbox"}
        ),
        content_type="application/json",
        **auth_headers(user["token"]),
    ).json()
    return {"client": client, "user": user, "org_id": org["id"], "project": project}


def _provision(wallet: Wallet) -> Wallet:
    """Simulate completed provisioning: group public keys recorded."""
    wallet.ecdsa_public_key = GENERATOR_HEX
    wallet.ed25519_public_key = ED25519_HEX
    wallet.ecdsa_key_ref = "wallet-test-ecdsa"
    wallet.ed25519_key_ref = "wallet-test-ed25519"
    wallet.status = Wallet.Status.ACTIVE
    wallet.save()
    return wallet


def _dashboard_post(ctx: dict, payload: dict):
    return ctx["client"].post(
        "/api/v1/deposit-addresses",
        data=json.dumps(payload),
        content_type="application/json",
        **auth_headers(ctx["user"]["token"]),
    )


@pytest.mark.django_db
class TestDepositAddressByUid:
    def test_api_mode_uid_plus_chain_returns_address(self, ctx):
        key = make_api_key(ctx["client"], ctx["user"]["token"], ctx["project"]["id"], scopes=["addresses:write"])
        path = "/api/v1/deposit-addresses"
        body = json.dumps({"external_customer_id": "user-42", "network": "ethereum"}).encode()

        # First call creates the UID's wallet; unprovisioned -> 409,
        # and no address is fabricated.
        first = ctx["client"].post(
            path, data=body, content_type="application/json",
            **hmac_headers(key["secret"], key["key_id"], "POST", path, body),
        )
        assert first.status_code == 409, first.content
        wallet = Wallet.objects.get(
            project_id=ctx["project"]["id"], external_customer_id="user-42"
        )
        assert wallet.status == "provisioning"
        assert not Address.objects.filter(wallet=wallet).exists()

        _provision(wallet)
        body2 = json.dumps({"external_customer_id": "user-42", "network": "ethereum"}).encode()
        created = ctx["client"].post(
            path, data=body2, content_type="application/json",
            **hmac_headers(key["secret"], key["key_id"], "POST", path, body2),
        )
        assert created.status_code == 201, created.content
        data = created.json()
        assert data["address"] == EVM_ADDR
        assert data["external_customer_id"] == "user-42"
        assert data["created"] is True
        assert data["wallet_status"] == "active"

        again = ctx["client"].post(
            path, data=body2, content_type="application/json",
            **hmac_headers(key["secret"], key["key_id"], "POST", path, body2),
        )
        assert again.status_code == 200
        assert again.json()["address"] == EVM_ADDR
        assert again.json()["created"] is False

    def test_manual_mode_dashboard_uid_entry(self, ctx):
        wallet = Wallet.objects.create(
            project_id=ctx["project"]["id"], label="Customer user-7",
            external_customer_id="user-7",
        )
        _provision(wallet)
        resp = _dashboard_post(ctx, {
            "project_id": ctx["project"]["id"],
            "external_customer_id": "user-7",
            "network": "solana",
        })
        assert resp.status_code == 201, resp.content
        assert resp.json()["address"] == SOLANA_ADDR
        assert resp.json()["external_customer_id"] == "user-7"

    def test_validation_and_scopes(self, ctx):
        project_id = ctx["project"]["id"]
        reserved = _dashboard_post(ctx, {
            "project_id": project_id, "external_customer_id": "gas-station",
            "network": "ethereum",
        })
        assert reserved.status_code == 422
        unknown = _dashboard_post(ctx, {
            "project_id": project_id, "external_customer_id": "user-1",
            "network": "dogecoin",
        })
        assert unknown.status_code == 422
        blank = _dashboard_post(ctx, {
            "project_id": project_id, "external_customer_id": "  ",
            "network": "ethereum",
        })
        assert blank.status_code == 422

        read_key = make_api_key(ctx["client"], ctx["user"]["token"], project_id, scopes=["read"])
        path = "/api/v1/deposit-addresses"
        body = json.dumps({"external_customer_id": "user-9", "network": "ethereum"}).encode()
        forbidden = ctx["client"].post(
            path, data=body, content_type="application/json",
            **hmac_headers(read_key["secret"], read_key["key_id"], "POST", path, body),
        )
        assert forbidden.status_code == 403


@pytest.mark.django_db
class TestDepositAddressSearch:
    def _make_address(self, ctx, uid: str = "user-42") -> Address:
        wallet = Wallet.objects.create(
            project_id=ctx["project"]["id"], label=f"Customer {uid}",
            external_customer_id=uid,
        )
        _provision(wallet)
        resp = _dashboard_post(ctx, {
            "project_id": ctx["project"]["id"], "external_customer_id": uid,
            "network": "ethereum",
        })
        assert resp.status_code == 201, resp.content
        return Address.objects.get(id=resp.json()["id"])

    def test_search_by_address_finds_uid(self, ctx):
        address = self._make_address(ctx)
        resp = ctx["client"].get(
            "/api/v1/deposit-addresses",
            {"project_id": ctx["project"]["id"], "address": address.address},
            **auth_headers(ctx["user"]["token"]),
        )
        assert resp.status_code == 200
        rows = resp.json()["items"]
        assert len(rows) == 1
        assert rows[0]["external_customer_id"] == "user-42"
        assert rows[0]["wallet_status"] == "active"
        assert rows[0]["deposits"] == {"count": 0, "held_count": 0, "credited_totals": []}

    def test_search_by_uid_lists_all_addresses_with_deposit_summary(self, ctx):
        address = self._make_address(ctx)
        _dashboard_post(ctx, {
            "project_id": ctx["project"]["id"], "external_customer_id": "user-42",
            "network": "solana",
        })
        network = BlockchainNetwork.objects.get(slug="ethereum")
        asset = Asset.objects.get(network=network, symbol="ETH")
        ObservedDeposit.objects.create(
            network=network, address=address, wallet=address.wallet, asset=asset,
            tx_hash="0x" + "ab" * 32, occurrence=0, from_address="0x" + "11" * 20,
            amount=500, block_number=100, block_hash="0x" + "cd" * 32,
            status=ObservedDeposit.Status.CREDITED,
        )
        resp = ctx["client"].get(
            "/api/v1/deposit-addresses",
            {"project_id": ctx["project"]["id"], "external_customer_id": "user-42"},
            **auth_headers(ctx["user"]["token"]),
        )
        rows = resp.json()["items"]
        assert {r["network"] for r in rows} == {"ethereum", "solana"}
        eth_row = next(r for r in rows if r["network"] == "ethereum")
        assert eth_row["deposits"]["count"] == 1
        assert eth_row["deposits"]["credited_totals"] == [{"asset": "ETH", "amount": "500"}]

    def test_search_is_tenant_scoped(self, ctx):
        self._make_address(ctx)
        other = register_user(ctx["client"], "other@example.com")
        resp = ctx["client"].get(
            "/api/v1/deposit-addresses",
            {"project_id": ctx["project"]["id"], "external_customer_id": "user-42"},
            **auth_headers(other["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.django_db
class TestWalletCreationEnsuresGasSponsor:
    def test_wallet_creation_heals_missing_gas_station(self, ctx):
        from waas.modules.identity.models import User
        from waas.modules.organizations.models import Organization

        # A project created directly in the DB (pre-auto-setup era)
        # has no gas station; creating a wallet must establish one.
        org = Organization.objects.get(id=ctx["org_id"])
        owner = User.objects.get(email="owner@example.com")
        legacy = Project.objects.create(
            organization=org, name="Legacy", environment="sandbox", created_by=owner
        )
        assert not Wallet.objects.filter(
            project=legacy, external_customer_id="gas-station"
        ).exists()
        resp = ctx["client"].post(
            "/api/v1/wallets",
            data=json.dumps({"project_id": str(legacy.id), "label": "Ops"}),
            content_type="application/json",
            **auth_headers(ctx["user"]["token"]),
        )
        assert resp.status_code == 201, resp.content
        assert Wallet.objects.filter(
            project=legacy, external_customer_id="gas-station"
        ).exists()
        from waas.modules.gasstation.models import GasStation

        assert GasStation.objects.filter(project=legacy).count() == BlockchainNetwork.objects.count()
