"""Solana keys, addresses, and program-derived addresses (PDAs).

An address is the base58 form of a 32-byte Ed25519 public key.
Token custody uses **associated token accounts**: PDAs of the
Associated Token Account program with seeds
``[owner, token_program, mint]``. A PDA must lie *off* the Ed25519
curve (so no private key exists for it); derivation therefore
needs an on-curve test, implemented here from the curve equation
``-x² + y² = 1 + d·x²y² (mod 2²⁵⁵ − 19)``.
"""

from __future__ import annotations

import hashlib

from . import base58

SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM = "AToken1vXN1sVvyToCVVZ7PBTnbAKDD7TcUJDYcYsASW"

_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_PDA_MARKER = b"ProgramDerivedAddress"


class SolanaKeyError(ValueError):
    """Raised for malformed keys/addresses or impossible PDAs."""


def validate_pubkey_bytes(data: bytes) -> bytes:
    if len(data) != 32:
        raise SolanaKeyError("a Solana public key must be 32 bytes")
    return data


def address_from_public_key(public_key: bytes) -> str:
    return base58.encode(validate_pubkey_bytes(public_key))


def public_key_from_address(address: str) -> bytes:
    try:
        raw = base58.decode(address)
    except base58.Base58Error as exc:
        raise SolanaKeyError(f"invalid Solana address: {exc}") from exc
    return validate_pubkey_bytes(raw)


def is_valid_address(address: str) -> bool:
    try:
        public_key_from_address(address)
        return True
    except SolanaKeyError:
        return False


def is_on_curve(point: bytes) -> bool:
    """True if the 32-byte compressed Ed25519 point decompresses —
    the check Solana applies to reject PDA candidates."""
    if len(point) != 32:
        return False
    y = int.from_bytes(point, "little") & ((1 << 255) - 1)
    sign = point[31] >> 7
    if y >= _P:
        return False
    y2 = (y * y) % _P
    denominator = (_D * y2 + 1) % _P
    if denominator == 0:
        return False
    x2 = ((y2 - 1) * pow(denominator, _P - 2, _P)) % _P
    if x2 == 0:
        return sign == 0
    # Euler criterion: x² is a quadratic residue mod p.
    return pow(x2, (_P - 1) // 2, _P) == 1


def create_program_address(seeds: list[bytes], program_id: bytes) -> bytes:
    """sha256(seeds ‖ program_id ‖ marker); must be off-curve."""
    digest = hashlib.sha256(b"".join(seeds) + program_id + _PDA_MARKER).digest()
    if is_on_curve(digest):
        raise SolanaKeyError("seed set produces an on-curve address (not a PDA)")
    return digest


def find_program_address(seeds: list[bytes], program_id: bytes) -> tuple[bytes, int]:
    """The canonical PDA: the first bump (255 down to 0) whose
    create_program_address succeeds."""
    for bump in range(255, -1, -1):
        try:
            address = create_program_address([*seeds, bytes([bump])], program_id)
            return address, bump
        except SolanaKeyError:
            continue
    raise SolanaKeyError("no viable program address bump found")


def associated_token_address(*, owner: str, mint: str, token_program: str = TOKEN_PROGRAM) -> str:
    """The associated token account address for (owner, mint)."""
    owner_bytes = public_key_from_address(owner)
    mint_bytes = public_key_from_address(mint)
    program_bytes = public_key_from_address(ASSOCIATED_TOKEN_PROGRAM)
    address, _bump = find_program_address(
        [owner_bytes, public_key_from_address(token_program), mint_bytes],
        program_bytes,
    )
    return base58.encode(address)
