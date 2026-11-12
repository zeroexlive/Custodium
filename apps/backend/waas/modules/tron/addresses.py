"""TRON address handling.

A TRON account address is 21 bytes: the constant ``0x41`` prefix
plus the last 20 bytes of ``keccak256(uncompressed public key)`` —
the same key material as EVM, a different envelope. Two display
forms exist:

- **hex form**: the 21 bytes hex-encoded (``41…``, 42 chars) — the
  form the HTTP APIs and this codebase's address normalisation use;
- **Base58Check form**: ``base58(21 bytes + first 4 bytes of
  double-SHA256)`` (``T…``) — the form users see.

Conversions here are exact and checksum-verified; an invalid
checksum raises instead of returning a near-miss address.
"""

from __future__ import annotations

import hashlib

from waas.modules.evm import keys

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}
ADDRESS_PREFIX = 0x41


class TronAddressError(ValueError):
    """Raised when a TRON address is malformed or fails checksum."""


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def base58_encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    chars = []
    while number > 0:
        number, rem = divmod(number, 58)
        chars.append(_B58_ALPHABET[rem])
    for b in data:
        if b == 0:
            chars.append("1")
        else:
            break
    return "".join(reversed(chars))


def base58_decode(text: str) -> bytes:
    number = 0
    for char in text:
        if char not in _B58_INDEX:
            raise TronAddressError(f"invalid base58 character: {char!r}")
        number = number * 58 + _B58_INDEX[char]
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading = len(text) - len(text.lstrip("1"))
    return b"\x00" * leading + body


def base58check_encode(payload: bytes) -> str:
    checksum = _sha256(_sha256(payload))[:4]
    return base58_encode(payload + checksum)


def base58check_decode(text: str) -> bytes:
    raw = base58_decode(text)
    if len(raw) < 5:
        raise TronAddressError("Base58Check value too short")
    payload, checksum = raw[:-4], raw[-4:]
    if _sha256(_sha256(payload))[:4] != checksum:
        raise TronAddressError("Base58Check checksum mismatch")
    return payload


def hex_to_base58(hex_address: str) -> str:
    """``41…`` hex (42 chars) -> Base58Check (``T…``)."""
    raw = bytes.fromhex(hex_address.removeprefix("0x"))
    if len(raw) != 21 or raw[0] != ADDRESS_PREFIX:
        raise TronAddressError("hex form must be 21 bytes starting with 0x41")
    return base58check_encode(raw)


def base58_to_hex(address: str) -> str:
    """Base58Check (``T…``) -> ``41…`` hex (lowercase, no 0x)."""
    payload = base58check_decode(address)
    if len(payload) != 21 or payload[0] != ADDRESS_PREFIX:
        raise TronAddressError("not a TRON account address")
    return payload.hex()


def normalize_to_hex(address: str) -> str:
    """Accept either display form and return the ``41…`` hex form."""
    text = address.strip()
    if text.lower().startswith("41") and len(text) == 42:
        try:
            raw = bytes.fromhex(text)
        except ValueError:
            raw = b""
        if len(raw) == 21 and raw[0] == ADDRESS_PREFIX:
            return text.lower()
    return base58_to_hex(text)


def is_valid(address: str) -> bool:
    try:
        normalize_to_hex(address)
        return True
    except (TronAddressError, ValueError):
        return False


def address_from_public_key(public_key: bytes) -> str:
    """Derive the Base58Check address from a 64- or 65-byte
    secp256k1 public key (the MPC group key material)."""
    return hex_to_base58(hex_from_public_key(public_key))


def hex_from_public_key(public_key: bytes) -> str:
    # The EVM helper returns EIP-55 checksummed (mixed-case) hex;
    # TRON's hex form is canonical lowercase.
    body = keys.address_from_public_key(public_key)
    return "41" + body[2:].lower()
