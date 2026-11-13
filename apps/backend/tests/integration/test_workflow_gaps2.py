"""William's workflow (2026-11-14): automatic gas-station setup at
project creation + the create-address API.

- Creating a project creates its "Gas Station" funding wallet and
  one station per seeded network (family defaults), so the client
  has per-network top-up addresses as soon as the wallet is
  provisioned.
- POST /wallets/{id}/addresses {network} returns the existing
  address or derives + records it from the wallet's stored group
  public key; unprovisioned wallets get an honest 409.
- Provisioning persists the group public keys used for that
  derivation (public material only).
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
    make_org_project,
    register_user,
)
from waas.modules.gasstation.models import GasStation
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
    return {"client": client, "user": user, "org_id": org["id"]}


def _create_project(ctx: dict, name: str = "Main") -> dict:
    resp = ctx["client"].post(
        "/api/v1/projects",
        data=json.dumps(
            {"organization_id": ctx["org_id"], "name": name, "environment": "sandbox"}
        ),
        content_type="application/json",
        **auth_headers(ctx["user"]["token"]),
    )
    assert resp.status_code == 201, resp.content
    return resp.json()


@pytest.mark.django_db
class TestAutoGasStationSetup:
    def test_project_creation_creates_funding_wallet_and_stations(self, ctx):
        project = _create_project(ctx)
        wallet = Wallet.objects.get(
            project_id=project["id"], external_customer_id="gas-station"
        )
        assert wallet.label == "Gas Station"
        assert wallet.status == "provisioning"
        stations = GasStation.objects.filter(project_id=project["id"])
        assert stations.count() == BlockchainNetwork.objects.count()
        assert all(s.funding_wallet_id == wallet.id for s in stations)
        by_slug = {s.network.slug: s for s in stations.select_related("network")}
        assert int(by_slug["ethereum"].topup_amount) == 2_000_000_000_000_000
        assert int(by_slug["ethereum"].min_native_balance) == 500_000_000_000_000
        assert int(by_slug["solana"].topup_amount) == 50_000_000
        assert int(by_slug["tron"].topup_amount) == 50_000_000
        assert all(s.enabled for s in stations)

    def test_stations_visible_via_api_with_null_top_up_until_provisioned(self, ctx):
        project = _create_project(ctx)
        resp = ctx["client"].get(
            f"/api/v1/gas-stations?project_id={project['id']}",
            **auth_headers(ctx["user"]["token"]),
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"] if isinstance(body, dict) else body
        assert len(items) == BlockchainNetwork.objects.count()
        assert all(item["top_up_address"] is None for item in items)

    def test_setup_is_idempotent(self, ctx):
        project = _create_project(ctx)
        from waas.modules.gasstation.services import setup_project_gas_station

        proj = Project.objects.get(id=project["id"])
        _, created = setup_project_gas_station(proj)
        assert created == 0
        assert GasStation.objects.filter(project=proj).count() == (
            BlockchainNetwork.objects.count()
        )
        assert Wallet.objects.filter(
            project=proj, external_customer_id="gas-station"
        ).count() == 1


@pytest.fixture
def api_ctx(ctx):
    ids = make_org_project(ctx["client"], ctx["user"]["token"])
    return {**ctx, "project_id": ids["project"]["id"]}


def _post_address(ctx: dict, key: dict, wallet_id, network: str):
    path = f"/api/v1/wallets/{wallet_id}/addresses"
    body = json.dumps({"network": network}).encode()
    return ctx["client"].post(
        path, data=body, content_type="application/json",
        **hmac_headers(key["secret"], key["key_id"], "POST", path, body),
    )


def _wallet(project_id: str, **kwargs) -> Wallet:
    defaults = {"label": "Customer 1", "external_customer_id": "cust_1"}
    defaults.update(kwargs)
    return Wallet.objects.create(project_id=project_id, **defaults)


@pytest.mark.django_db
class TestCreateAddressApi:
    def test_unprovisioned_wallet_gets_409(self, api_ctx):
        key = make_api_key(
            api_ctx["client"], api_ctx["user"]["token"], api_ctx["project_id"],
            scopes=["wallets:write"],
        )
        wallet = _wallet(api_ctx["project_id"])
        resp = _post_address(api_ctx, key, wallet.id, "ethereum")
        assert resp.status_code == 409
        assert "not provisioned" in resp.json()["detail"]

    def test_derives_records_and_returns_existing(self, api_ctx):
        key = make_api_key(
            api_ctx["client"], api_ctx["user"]["token"], api_ctx["project_id"],
            scopes=["addresses:write"],
        )
        wallet = _wallet(
            api_ctx["project_id"], status="active",
            ecdsa_public_key=GENERATOR_HEX, ed25519_public_key=ED25519_HEX,
            ecdsa_key_ref="k-ecdsa", ed25519_key_ref="k-ed",
        )
        resp = _post_address(api_ctx, key, wallet.id, "ethereum")
        assert resp.status_code == 201, resp.content
        assert resp.json()["address"] == EVM_ADDR
        assert Address.objects.filter(wallet=wallet, network__slug="ethereum").count() == 1

        again = _post_address(api_ctx, key, wallet.id, "ethereum")
        assert again.status_code == 200
        assert again.json()["address"] == EVM_ADDR
        assert Address.objects.filter(wallet=wallet).count() == 1

        resp = _post_address(api_ctx, key, wallet.id, "solana")
        assert resp.status_code == 201, resp.content
        assert resp.json()["address"] == SOLANA_ADDR

    def test_unknown_network_422_and_read_scope_403(self, api_ctx):
        wallet = _wallet(
            api_ctx["project_id"], status="active",
            ecdsa_public_key=GENERATOR_HEX, ed25519_public_key=ED25519_HEX,
        )
        write_key = make_api_key(
            api_ctx["client"], api_ctx["user"]["token"], api_ctx["project_id"],
            scopes=["wallets:write"],
        )
        resp = _post_address(api_ctx, write_key, wallet.id, "dogechain")
        assert resp.status_code == 422

        read_key = make_api_key(
            api_ctx["client"], api_ctx["user"]["token"], api_ctx["project_id"],
            scopes=["read"],
        )
        resp = _post_address(api_ctx, read_key, wallet.id, "ethereum")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestProvisioningPersistsPublicKeys:
    def test_public_keys_recorded(self, ctx, monkeypatch):
        ids = make_org_project(ctx["client"], ctx["user"]["token"])
        wallet = _wallet(ids["project"]["id"])
        from waas.modules.wallets import provisioning

        metas = {
            provisioning.key_id_for(wallet, "ecdsa"): {
                "curve": "secp256k1", "public_key": GENERATOR_HEX,
            },
            provisioning.key_id_for(wallet, "ed25519"): {
                "curve": "ed25519", "public_key": ED25519_HEX,
            },
        }
        monkeypatch.setattr(provisioning, "signer_enabled", lambda: True)
        monkeypatch.setattr(
            provisioning, "_get_or_create_key",
            lambda client, key_id, curve, t: metas[key_id],
        )
        provisioning.provision_wallet(wallet, client=object())
        wallet.refresh_from_db()
        assert wallet.ecdsa_public_key == GENERATOR_HEX
        assert wallet.ed25519_public_key == ED25519_HEX
