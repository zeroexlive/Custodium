"""Client for the Custodium MPC signer service (Rust,
`services/mpc/crates/signer_service`).

The signer service performs real threshold ceremonies (cggmp24
ECDSA + FROST Ed25519) across its own participant nodes and holds
all key shares in its own encrypted stores. This client is the
ONLY bridge: Django sends key ids, digests and messages, and
receives public keys and signatures. No key material ever crosses
in either direction.

Activation is deliberately hard to do by accident. The dispatch
factories keep returning the fail-closed `UnavailableSigner`s
unless BOTH hold:

* `MPC_SIGNER_ENABLED` is explicitly true, and
* `MPC_SIGNER_URL` points at a signer node (its coordinator API).

Even then, Custodium's recorded status stays "not Security
Reviewed / not Production Approved" until the independent
cryptographic review (docs/mpc/review/) passes — enabling this
gate is an operator decision that the readiness checklist tracks
as a review-gated action, not a code default.
"""

from __future__ import annotations

import base64

import httpx
from django.conf import settings

from waas.modules.evm.signing import SigningUnavailable as EcdsaUnavailable
from waas.modules.solana.signing import SigningUnavailable as Ed25519Unavailable

# Signing a digest/message runs a live multi-party ceremony;
# allow generous but bounded time.
SIGN_TIMEOUT_SECONDS = 300.0
READ_TIMEOUT_SECONDS = 30.0


def key_id_for(wallet) -> str:
    """The signer-service key id for a wallet (deterministic)."""
    return f"wallet-{wallet.id}"


def signer_enabled() -> bool:
    """True only when the operator has explicitly opened the gate."""
    return bool(
        getattr(settings, "MPC_SIGNER_ENABLED", False)
        and getattr(settings, "MPC_SIGNER_URL", "")
    )


class SignerServiceClient:
    """Thin HTTP client for one signer node's coordinator API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            # Internal service: never route through environment
            # proxies (trust_env would also make requests depend on
            # ambient proxy variables).
            trust_env=False,
        )

    def get_key(self, key_id: str) -> dict:
        try:
            resp = self._client.get(
                f"/v1/keys/{key_id}", timeout=READ_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as exc:
            raise EcdsaUnavailable(f"signer service unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise EcdsaUnavailable(
                f"signer service returned {resp.status_code} for key lookup"
            )
        return resp.json()

    def create_key(self, key_id: str, curve: str, t: int) -> dict:
        """Provision a new threshold key (operator action; runs a
        DKG ceremony across the signer nodes)."""
        try:
            resp = self._client.post(
                "/v1/keys",
                json={"key_id": key_id, "curve": curve, "t": t},
                timeout=1800.0,
            )
        except httpx.HTTPError as exc:
            raise EcdsaUnavailable(f"signer service unreachable: {exc}") from exc
        if resp.status_code != 201:
            raise EcdsaUnavailable(
                f"signer service key creation failed: {resp.status_code}"
            )
        return resp.json()

    def sign_ecdsa(self, key_id: str, digest: bytes) -> tuple[int, int]:
        meta = self.get_key(key_id)
        signers = list(range(int(meta["t"])))
        try:
            resp = self._client.post(
                f"/v1/keys/{key_id}/sign",
                json={"signers": signers, "digest_hex": digest.hex()},
                timeout=SIGN_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise EcdsaUnavailable(f"signer service unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise EcdsaUnavailable(
                f"signer service signing failed: {resp.status_code}"
            )
        body = resp.json()
        return int(body["r"], 16), int(body["s"], 16)

    def sign_ed25519(self, key_id: str, message: bytes) -> bytes:
        try:
            meta = self.get_key(key_id)
        except EcdsaUnavailable as exc:
            raise Ed25519Unavailable(str(exc)) from exc
        signers = list(range(int(meta["t"])))
        try:
            resp = self._client.post(
                f"/v1/keys/{key_id}/sign",
                json={
                    "signers": signers,
                    "message_b64": base64.b64encode(message).decode(),
                },
                timeout=SIGN_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise Ed25519Unavailable(
                f"signer service unreachable: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise Ed25519Unavailable(
                f"signer service signing failed: {resp.status_code}"
            )
        return bytes.fromhex(resp.json()["signature"])


def default_client() -> SignerServiceClient:
    return SignerServiceClient(
        settings.MPC_SIGNER_URL,
        getattr(settings, "MPC_SIGNER_TOKEN", ""),
    )


class RemoteEcdsaSigner:
    """`SignerPort` backed by the MPC signer service (ECDSA)."""

    def __init__(self, client: SignerServiceClient) -> None:
        self._client = client

    def wallet_public_key(self, wallet) -> bytes:
        meta = self._client.get_key(key_id_for(wallet))
        if meta.get("curve") != "secp256k1":
            raise EcdsaUnavailable("wallet key is not an ECDSA key")
        return bytes.fromhex(meta["public_key"])

    def sign_digest(self, wallet, digest: bytes) -> tuple[int, int]:
        if len(digest) != 32:
            raise EcdsaUnavailable("digest must be 32 bytes")
        return self._client.sign_ecdsa(key_id_for(wallet), digest)


class RemoteEd25519Signer:
    """`Ed25519SignerPort` backed by the MPC signer service (FROST)."""

    def __init__(self, client: SignerServiceClient) -> None:
        self._client = client

    def wallet_public_key(self, wallet) -> bytes:
        try:
            meta = self._client.get_key(key_id_for(wallet))
        except EcdsaUnavailable as exc:
            raise Ed25519Unavailable(str(exc)) from exc
        if meta.get("curve") != "ed25519":
            raise Ed25519Unavailable("wallet key is not an Ed25519 key")
        return bytes.fromhex(meta["public_key"])

    def sign_message(self, wallet, message: bytes) -> bytes:
        return self._client.sign_ed25519(key_id_for(wallet), message)
