"""MPC signer service client + activation gate (post-roadmap).

The gate is the safety property: factories must keep returning the
fail-closed signers unless the operator explicitly enables the
signer AND configures its URL. The client contract is exercised
against an httpx MockTransport standing in for the Rust service.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from django.test import override_settings

from waas.modules.evm.signing import SigningUnavailable as EcdsaUnavailable
from waas.modules.evm.signing import UnavailableSigner
from waas.modules.mpcsigner.client import (
    RemoteEcdsaSigner,
    RemoteEd25519Signer,
    SignerServiceClient,
    key_id_for,
)
from waas.modules.operations.dispatch import (
    default_ecdsa_signer,
    default_ed25519_signer,
)
from waas.modules.solana.signing import (
    SigningUnavailable as Ed25519Unavailable,
)
from waas.modules.solana.signing import UnavailableEd25519Signer

WALLET = SimpleNamespace(id=uuid.UUID("12345678-1234-5678-1234-567812345678"))
KEY_ID = key_id_for(WALLET)

ECDSA_META = {
    "key_id": KEY_ID,
    "curve": "secp256k1",
    "t": 2,
    "n": 3,
    "public_key": "04" + "ab" * 64,
}
ED25519_META = {
    "key_id": KEY_ID,
    "curve": "ed25519",
    "t": 2,
    "n": 3,
    "public_key": "cd" * 32,
}


def make_client(handler) -> SignerServiceClient:
    return SignerServiceClient(
        "http://signer.test", "token", transport=httpx.MockTransport(handler)
    )


class TestGate:
    def test_factories_fail_closed_by_default(self):
        assert isinstance(default_ecdsa_signer(), UnavailableSigner)
        assert isinstance(default_ed25519_signer(), UnavailableEd25519Signer)

    @override_settings(MPC_SIGNER_ENABLED=True, MPC_SIGNER_URL="")
    def test_enabled_without_url_still_fails_closed(self):
        assert isinstance(default_ecdsa_signer(), UnavailableSigner)
        assert isinstance(default_ed25519_signer(), UnavailableEd25519Signer)

    @override_settings(MPC_SIGNER_ENABLED=False, MPC_SIGNER_URL="http://x")
    def test_url_without_enable_still_fails_closed(self):
        assert isinstance(default_ecdsa_signer(), UnavailableSigner)

    @override_settings(
        MPC_SIGNER_ENABLED=True,
        MPC_SIGNER_URL="http://signer.test",
        MPC_SIGNER_TOKEN="t",
    )
    def test_both_conditions_open_the_gate(self):
        assert isinstance(default_ecdsa_signer(), RemoteEcdsaSigner)
        assert isinstance(default_ed25519_signer(), RemoteEd25519Signer)


class TestRemoteEcdsaSigner:
    def test_public_key_and_sign_digest(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen[request.url.path] = request
            if request.method == "GET":
                return httpx.Response(200, json=ECDSA_META)
            body = json.loads(request.content)
            seen["sign_body"] = body
            return httpx.Response(
                200, json={"r": "0x" + "11" * 32, "s": "0x" + "22" * 32}
            )

        signer = RemoteEcdsaSigner(make_client(handler))
        public_key = signer.wallet_public_key(WALLET)
        assert len(public_key) == 65 and public_key[0] == 0x04
        r, s = signer.sign_digest(WALLET, b"\x07" * 32)
        assert r == int("11" * 32, 16)
        assert s == int("22" * 32, 16)
        # The default quorum is the first t=2 parties.
        assert seen["sign_body"]["signers"] == [0, 1]
        assert seen["sign_body"]["digest_hex"] == "07" * 32

    def test_service_error_fails_closed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"error": "session failed"})

        signer = RemoteEcdsaSigner(make_client(handler))
        with pytest.raises(EcdsaUnavailable):
            signer.wallet_public_key(WALLET)

    def test_unreachable_service_fails_closed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        signer = RemoteEcdsaSigner(make_client(handler))
        with pytest.raises(EcdsaUnavailable):
            signer.sign_digest(WALLET, b"\x00" * 32)


class TestRemoteEd25519Signer:
    def test_public_key_and_sign_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json=ED25519_META)
            body = json.loads(request.content)
            assert body["signers"] == [0, 1]
            return httpx.Response(200, json={"signature": "ef" * 64})

        signer = RemoteEd25519Signer(make_client(handler))
        assert signer.wallet_public_key(WALLET) == bytes.fromhex("cd" * 32)
        signature = signer.sign_message(WALLET, b"message")
        assert signature == bytes.fromhex("ef" * 64)

    def test_service_error_raises_ed25519_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"error": "nope"})

        signer = RemoteEd25519Signer(make_client(handler))
        with pytest.raises(Ed25519Unavailable):
            signer.sign_message(WALLET, b"message")
