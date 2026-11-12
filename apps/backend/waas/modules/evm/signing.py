"""The signing boundary for EVM transactions (Phase 4).

Custodium's backend NEVER holds key material and cannot sign: the
only thing it may do is hand a 32-byte digest and the wallet's
public key to a signer through this port and receive (r, s) back.

There is deliberately NO working implementation in this codebase
yet. Production signing stays disabled until the MPC integration
has passed the independent cryptographic review (Phase 3 record:
`docs/mpc/phase-3-evaluation.md`, review package `docs/mpc/review/`
— not commissioned). `UnavailableSigner` is therefore the only
implementation wired anywhere, and it fails closed: the withdrawal
pipeline treats SigningUnavailable as a clean abort (reservation
released, transaction marked failed) rather than an exception path.
"""

from __future__ import annotations

from typing import Protocol

from waas.modules.wallets.models import Wallet


class SigningUnavailable(RuntimeError):
    """No signer is available for this wallet (fail-closed)."""


class SignerPort(Protocol):
    """What a reviewed MPC signer integration must provide."""

    def wallet_public_key(self, wallet: Wallet) -> bytes:
        """The wallet's 64/65-byte secp256k1 public key."""
        ...

    def sign_digest(self, wallet: Wallet, digest: bytes) -> tuple[int, int]:
        """Threshold-sign a 32-byte digest; returns (r, s)."""
        ...


class UnavailableSigner:
    """Fail-closed signer: the state of the world until the MPC
    review gate opens. Every call raises SigningUnavailable."""

    def wallet_public_key(self, wallet: Wallet) -> bytes:
        raise SigningUnavailable(
            "MPC signer integration is disabled pending independent cryptographic review"
        )

    def sign_digest(self, wallet: Wallet, digest: bytes) -> tuple[int, int]:
        raise SigningUnavailable(
            "MPC signer integration is disabled pending independent cryptographic review"
        )
