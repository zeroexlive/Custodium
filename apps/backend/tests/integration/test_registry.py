"""Network/asset registry: seeded identities must be exact, especially USDT
classification (BSC USDT is Binance-Peg, NOT issuer-native Tether)."""
from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import Client

from tests.conftest import auth_headers, register_user

pytestmark = pytest.mark.django_db


@pytest.fixture()
def seeded(client: Client) -> str:
    call_command("seed_networks_assets")
    user = register_user(client, "registry@example.com")
    return user["access_token"]


def test_networks_seeded(client: Client, seeded: str) -> None:
    resp = client.get("/api/v1/networks", **auth_headers(seeded))
    assert resp.status_code == 200
    slugs = {n["slug"] for n in resp.json()["items"]}
    assert {"ethereum", "bsc", "tron", "solana", "ton"} <= slugs
    families = {n["slug"]: n["signature_family"] for n in resp.json()["items"]}
    assert families["ethereum"] == "ecdsa_secp256k1"
    assert families["solana"] == "ed25519"
    assert families["ton"] == "ed25519"


def test_usdt_identities_exact(client: Client, seeded: str) -> None:
    resp = client.get("/api/v1/assets", **auth_headers(seeded))
    assert resp.status_code == 200
    usdt = {
        (a["network"]): a for a in resp.json()["items"] if a["symbol"] == "USDT"
    }
    assert usdt["ethereum"]["contract_or_mint_address"] == "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    assert usdt["ethereum"]["decimals"] == 6
    assert usdt["ethereum"]["issuer_classification"] == "issuer_native"
    # The trap the spec calls out: BSC USDT must NOT be issuer-native.
    assert usdt["bsc"]["contract_or_mint_address"] == "0x55d398326f99059fF775485246999027B3197955"
    assert usdt["bsc"]["decimals"] == 18
    assert usdt["bsc"]["issuer_classification"] == "bridged_pegged"
    assert usdt["tron"]["contract_or_mint_address"] == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    assert usdt["solana"]["contract_or_mint_address"] == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    assert usdt["ton"]["contract_or_mint_address"] == "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
    # Nothing may accept deposits/withdrawals before indexer + MPC phases.
    for asset in resp.json()["items"]:
        assert asset["deposit_enabled"] is False
        assert asset["withdrawal_enabled"] is False


def test_phase_gates_return_501(client: Client, seeded: str) -> None:
    lookup = client.get(
        "/api/v1/transactions/lookup?network=ethereum&hash=0xabc", **auth_headers(seeded)
    )
    assert lookup.status_code == 501
    sweep = client.get("/api/v1/sweep-destination-endpoint", **auth_headers(seeded))
    assert sweep.status_code == 501
