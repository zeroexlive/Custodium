"""Signer-backed wallet provisioning (post-roadmap).

The signer service is stood in for by an httpx MockTransport that
behaves like the real coordinator API (404 before creation, 201 on
create, 409 on re-create). The group public keys are FIXED test
vectors, so the derived addresses are pinned to values computed
independently of the provisioning code:

* ECDSA group key = the secp256k1 generator point. Its EVM address
  0x7E5F...5Bdf is the well-known address of private key 1 — an
  external check on the whole keccak/EIP-55 path.
* The TRON/Solana/TON expectations were produced by the family
  modules' canonical helpers, which carry their own golden tests
  (TRON USDT pair both directions, Solana base58 vectors, TON
  differentially verified against @ton/ton in Phase 8); here they
  pin the WIRING — right key, right family, right network rows.
"""
from __future__ import annotations

import json

import httpx
import pytest
from django.core.management import call_command
from django.test import Client, override_settings

from tests.conftest import auth_headers, make_org_project, register_user
from waas.modules.audit.models import AuditEvent
from waas.modules.mpcsigner.client import SignerServiceClient, key_id_for
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.wallets.models import Address, Wallet
from waas.modules.wallets.provisioning import (
    ProvisioningUnavailable,
    provision_wallet,
)

GENERATOR_POINT = bytes.fromhex(
    "04"
    "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
    "483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8"
)
ED25519_KEY = bytes([0x11] * 32)

EXPECTED = {
    "evm": "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf",
    "tron": "TMVQGm1qAQYVdetCeGRRkTWYYrLXuHK2HC",
    "solana": "29d2S7vB453rNYFdR5Ycwt7y9haRT5fwVwL9zTmBhfV2",
    "ton": "0:80c0eae40a5e9c3e2feb88224053706adc9cc2b1d1a0dd203cfdbfadefa6aa06",
}
FAMILY_BY_SLUG = {
    "ethereum": "evm",
    "ethereum-sepolia": "evm",
    "bsc": "evm",
    "bsc-testnet": "evm",
    "tron": "tron",
    "tron-nile": "tron",
    "solana": "solana",
    "solana-devnet": "solana",
    "ton": "ton",
    "ton-testnet": "ton",
}


class FakeSignerService:
    """In-memory stand-in for the signer coordinator API."""

    def __init__(self) -> None:
        self.keys: dict[str, dict] = {}
        self.create_calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/v1/keys":
            body = json.loads(request.content)
            key_id = body["key_id"]
            self.create_calls.append(key_id)
            if key_id in self.keys:
                return httpx.Response(409, json={"error": "key already exists"})
            public_key = (
                GENERATOR_POINT.hex()
                if body["curve"] == "secp256k1"
                else ED25519_KEY.hex()
            )
            self.keys[key_id] = {
                "key_id": key_id,
                "curve": body["curve"],
                "t": body["t"],
                "n": 3,
                "public_key": public_key,
            }
            return httpx.Response(201, json=self.keys[key_id])
        if request.method == "GET" and path.startswith("/v1/keys/"):
            key_id = path.rsplit("/", 1)[1]
            if key_id not in self.keys:
                return httpx.Response(404, json={"error": "unknown key"})
            return httpx.Response(200, json=self.keys[key_id])
        return httpx.Response(404, json={"error": "no route"})

    def client(self) -> SignerServiceClient:
        return SignerServiceClient(
            "http://signer.test", "token", transport=httpx.MockTransport(self.handler)
        )


def make_wallet(client: Client, token: str) -> tuple[dict, Wallet]:
    call_command("seed_networks_assets")
    ids = make_org_project(client, token)
    resp = client.post(
        "/api/v1/wallets",
        data=json.dumps(
            {"project_id": ids["project"]["id"], "label": "Customer 1"}
        ),
        content_type="application/json",
        **auth_headers(token),
    )
    assert resp.status_code == 201, resp.content
    return ids, Wallet.objects.get(id=resp.json()["id"])


GATE_OPEN = override_settings(
    MPC_SIGNER_ENABLED=True, MPC_SIGNER_URL="http://signer.test", MPC_SIGNER_TOKEN="t"
)


@pytest.mark.django_db
class TestProvisioningService:
    def test_gate_closed_leaves_wallet_provisioning(self, client: Client):
        user = register_user(client, "prov-closed@example.com")
        _, wallet = make_wallet(client, user["token"])
        with pytest.raises(ProvisioningUnavailable, match="gate is closed"):
            provision_wallet(wallet, client=FakeSignerService().client())
        wallet.refresh_from_db()
        assert wallet.status == Wallet.Status.PROVISIONING
        assert Address.objects.filter(wallet=wallet).count() == 0

    @GATE_OPEN
    def test_provision_creates_keys_addresses_and_activates(self, client: Client):
        user = register_user(client, "prov-open@example.com")
        _, wallet = make_wallet(client, user["token"])
        service = FakeSignerService()
        result = provision_wallet(wallet, client=service.client())
        assert result.status == Wallet.Status.ACTIVE
        assert result.ecdsa_key_ref == key_id_for(wallet, "ecdsa")
        assert result.ed25519_key_ref == key_id_for(wallet, "ed25519")
        assert sorted(service.create_calls) == sorted(
            [result.ecdsa_key_ref, result.ed25519_key_ref]
        )
        # One address per seeded network, each the family address.
        networks = BlockchainNetwork.objects.all()
        assert networks.count() == 10
        addresses = {
            a.network.slug: a.address for a in Address.objects.filter(wallet=wallet)
        }
        assert len(addresses) == 10
        for slug, family in FAMILY_BY_SLUG.items():
            assert addresses[slug] == EXPECTED[family], slug
        assert AuditEvent.objects.filter(event_type="wallet.provisioned").count() == 1

    @GATE_OPEN
    def test_reprovision_is_idempotent(self, client: Client):
        user = register_user(client, "prov-twice@example.com")
        _, wallet = make_wallet(client, user["token"])
        service = FakeSignerService()
        provision_wallet(wallet, client=service.client())
        again = provision_wallet(wallet, client=service.client())
        assert again.status == Wallet.Status.ACTIVE
        # No second DKG, no duplicate address rows.
        assert len(service.create_calls) == 2
        assert Address.objects.filter(wallet=wallet).count() == 10

    @GATE_OPEN
    def test_resume_after_partial_failure(self, client: Client):
        """Keys exist on the signer (created by an earlier crashed
        run) but the wallet was never activated: provisioning
        adopts the existing keys instead of re-running the DKG."""
        user = register_user(client, "prov-resume@example.com")
        _, wallet = make_wallet(client, user["token"])
        service = FakeSignerService()
        # Simulate the crashed earlier run: keys created, no DB writes.
        service.client().create_key(key_id_for(wallet, "ecdsa"), "secp256k1", 2)
        service.client().create_key(key_id_for(wallet, "ed25519"), "ed25519", 2)
        service.create_calls.clear()
        result = provision_wallet(wallet, client=service.client())
        assert result.status == Wallet.Status.ACTIVE
        assert service.create_calls == []
        assert Address.objects.filter(wallet=wallet).count() == 10

    @GATE_OPEN
    def test_frozen_wallet_cannot_be_provisioned(self, client: Client):
        user = register_user(client, "prov-frozen@example.com")
        _, wallet = make_wallet(client, user["token"])
        wallet.status = Wallet.Status.FROZEN
        wallet.save(update_fields=["status"])
        with pytest.raises(ProvisioningUnavailable, match="cannot be provisioned"):
            provision_wallet(wallet, client=FakeSignerService().client())

    @GATE_OPEN
    def test_signer_outage_leaves_wallet_untouched(self, client: Client):
        user = register_user(client, "prov-down@example.com")
        _, wallet = make_wallet(client, user["token"])

        def dead_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "node down"})

        dead = SignerServiceClient(
            "http://signer.test", "t", transport=httpx.MockTransport(dead_handler)
        )
        with pytest.raises(ProvisioningUnavailable):
            provision_wallet(wallet, client=dead)
        wallet.refresh_from_db()
        assert wallet.status == Wallet.Status.PROVISIONING
        assert Address.objects.filter(wallet=wallet).count() == 0


@pytest.mark.django_db
class TestProvisionEndpoint:
    def _patch_client(self, monkeypatch, service: FakeSignerService) -> None:
        monkeypatch.setattr(
            "waas.modules.wallets.provisioning.default_client",
            lambda: service.client(),
        )

    def test_gate_closed_returns_409(self, client: Client):
        user = register_user(client, "prov-ep-closed@example.com")
        _, wallet = make_wallet(client, user["token"])
        resp = client.post(
            f"/api/v1/wallets/{wallet.id}/provision",
            **auth_headers(user["token"]),
        )
        assert resp.status_code == 409
        wallet.refresh_from_db()
        assert wallet.status == Wallet.Status.PROVISIONING

    @GATE_OPEN
    def test_provision_via_endpoint(self, client: Client, monkeypatch):
        user = register_user(client, "prov-ep-open@example.com")
        _, wallet = make_wallet(client, user["token"])
        self._patch_client(monkeypatch, FakeSignerService())
        resp = client.post(
            f"/api/v1/wallets/{wallet.id}/provision",
            **auth_headers(user["token"]),
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["status"] == "active"
        assert body["key_generation"]["ecdsa_key_ref"] == key_id_for(wallet, "ecdsa")
        listing = client.get(
            f"/api/v1/wallets/{wallet.id}/addresses", **auth_headers(user["token"])
        )
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 10
        by_network = {i["network"]: i["address"] for i in items}
        assert by_network["ethereum"] == EXPECTED["evm"]
        assert by_network["ton-testnet"] == EXPECTED["ton"]
