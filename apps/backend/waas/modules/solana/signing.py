"""The Ed25519 signing port (Solana / TON side of the platform).

Ed25519 differs fundamentally from the ECDSA port: the signature
is 64 bytes computed over the *whole message* (no digest, no
recovery id). The production implementation is the Phase 3 FROST
threshold signer (frost-ed25519, pinned and evaluated); it stays
behind the same independent-review gate as ECDSA. Until that gate
opens, the only wired implementation is `UnavailableEd25519Signer`
— Solana withdrawals fail closed exactly like EVM/TRON ones, while
address derivation, indexing and deposits work without signing.
"""

from __future__ import annotations

from typing import Protocol

from waas.modules.wallets.models import Wallet


class SigningUnavailable(Exception):
    """No Ed25519 signer is available (production signing gated)."""


class Ed25519SignerPort(Protocol):
    def wallet_public_key(self, wallet: Wallet) -> bytes:
        """The wallet's 32-byte Ed25519 group public key."""
        ...

    def sign_message(self, wallet: Wallet, message: bytes) -> bytes:
        """Threshold-sign a complete message; returns the standard
        64-byte Ed25519 signature."""
        ...


class UnavailableEd25519Signer:
    """Fail-closed signer used until the reviewed FROST signer is
    wired in Phase 11/12."""

    def wallet_public_key(self, wallet: Wallet) -> bytes:
        raise SigningUnavailable(
            "Ed25519 key material is held by the MPC service; no signer is wired"
        )

    def sign_message(self, wallet: Wallet, message: bytes) -> bytes:
        raise SigningUnavailable(
            "production Ed25519 signing is disabled pending independent review"
        )
