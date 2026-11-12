"""Per-chain address parsing/normalisation (docs/blacklist/manual-blacklist.md §4).

Matching anywhere in the platform (blacklist, address registry) is done on
the normalised form. An address that cannot be parsed for its chain family
is an error, never a silent miss.
"""
from __future__ import annotations

import base64
import hashlib
import re

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {ch: i for i, ch in enumerate(_B58_ALPHABET)}

_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TON_RAW_RE = re.compile(r"^(-?\d+):([0-9a-fA-F]{64})$")

# Address format family by network slug (seeded networks; unknown slugs fall
# back to the network's signature family: ecdsa -> evm, ed25519 -> solana is
# NOT assumed — callers pass the family explicitly when they know it).
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


def family_for_slug(slug: str) -> str:
    try:
        return FAMILY_BY_SLUG[slug]
    except KeyError as exc:
        raise ValueError(f"No address family known for network slug '{slug}'") from exc


def b58decode(value: str) -> bytes:
    num = 0
    for ch in value:
        if ch not in _B58_INDEX:
            raise ValueError("Invalid base58 character")
        num = num * 58 + _B58_INDEX[ch]
    leading_zeros = len(value) - len(value.lstrip("1"))
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * leading_zeros + body


def b58check_decode(value: str) -> bytes:
    raw = b58decode(value)
    if len(raw) < 5:
        raise ValueError("Base58Check value too short")
    payload, checksum = raw[:-4], raw[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()
    if digest[:4] != checksum:
        raise ValueError("Base58Check checksum mismatch")
    return payload


def normalize_evm(raw: str) -> str:
    value = raw.strip()
    if not _EVM_RE.match(value):
        raise ValueError("Invalid EVM address (expected 0x + 40 hex chars)")
    return value.lower()


_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def normalize_tron(raw: str) -> str:
    """TRON Base58Check address -> canonical 21-byte hex (0x41 + account)."""
    value = raw.strip()
    hex_part = value[2:] if value.startswith("0x") else value
    if _HEX_RE.match(hex_part) and len(hex_part) in (40, 42):
        payload = bytes.fromhex(hex_part)
        if len(payload) == 21 and payload[0] == 0x41:
            return payload.hex()
        if len(payload) == 20:
            return (b"\x41" + payload).hex()
        raise ValueError("Invalid TRON hex address")
    payload = b58check_decode(value)
    if len(payload) != 21 or payload[0] != 0x41:
        raise ValueError("Invalid TRON address payload")
    return payload.hex()


def normalize_solana(raw: str) -> str:
    """Solana addresses are case-sensitive base58 of a 32-byte key."""
    value = raw.strip()
    decoded = b58decode(value)
    if len(decoded) != 32:
        raise ValueError("Invalid Solana address (must decode to 32 bytes)")
    return value


def _crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def normalize_ton(raw: str) -> str:
    """TON friendly (base64url) or raw form -> canonical raw 'workchain:hash'."""
    value = raw.strip()
    match = _TON_RAW_RE.match(value)
    if match:
        return f"{int(match.group(1))}:{match.group(2).lower()}"
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # noqa: BLE001 - any decode failure is a ValueError here
        raise ValueError("Invalid TON friendly address encoding") from exc
    # Friendly form: 1 byte tag + 1 byte workchain (signed) + 32 bytes hash + 2 bytes CRC16.
    if len(decoded) != 36:
        raise ValueError("Invalid TON friendly address length")
    if _crc16_xmodem(decoded[:34]) != int.from_bytes(decoded[34:36], "big"):
        raise ValueError("Invalid TON friendly address CRC")
    workchain = int.from_bytes(decoded[1:2], "big", signed=True)
    account_hash = decoded[2:34].hex()
    return f"{workchain}:{account_hash}"


_NORMALIZERS = {
    "evm": normalize_evm,
    "tron": normalize_tron,
    "solana": normalize_solana,
    "ton": normalize_ton,
}


def normalize_address(family: str, raw: str) -> str:
    try:
        normalizer = _NORMALIZERS[family]
    except KeyError as exc:
        raise ValueError(f"Unknown address family '{family}'") from exc
    if not raw or not raw.strip():
        raise ValueError("Address is required")
    return normalizer(raw)
