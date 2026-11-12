"""TON addresses: raw (`workchain:hex`) and user-friendly
(Base64url + flags + CRC16) forms.

Storage and matching use the raw form; the friendly form is
presentation. Per the Phase 0 chain design: workchain -1
(masterchain) addresses are rejected as user destinations, and
the testnet flag must match the network the address is used on.
"""

from __future__ import annotations

import base64

BOUNCEABLE_TAG = 0x11
NON_BOUNCEABLE_TAG = 0x51
TESTNET_FLAG = 0x80


class TonAddressError(ValueError):
    """Raised for malformed or disallowed TON addresses."""


def crc16(data: bytes) -> int:
    """CRC16-XMODEM (poly 0x1021, init 0) — the friendly-form checksum."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_raw(raw: str) -> tuple[int, bytes]:
    workchain_text, sep, hex_id = raw.partition(":")
    if not sep:
        raise TonAddressError("raw address must be '<workchain>:<hex>'")
    try:
        workchain = int(workchain_text)
        account_id = bytes.fromhex(hex_id)
    except ValueError as exc:
        raise TonAddressError(f"malformed raw address: {exc}") from exc
    if len(account_id) != 32:
        raise TonAddressError("account id must be 32 bytes")
    return workchain, account_id


def to_raw(workchain: int, account_id: bytes) -> str:
    if len(account_id) != 32:
        raise TonAddressError("account id must be 32 bytes")
    return f"{workchain}:{account_id.hex()}"


def friendly_to_raw(address: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(address + "=" * (-len(address) % 4))
    except Exception as exc:
        raise TonAddressError("not valid base64url") from exc
    if len(payload) != 36:
        raise TonAddressError("friendly address must decode to 36 bytes")
    expected_crc = int.from_bytes(payload[34:36], "big")
    if crc16(payload[:34]) != expected_crc:
        raise TonAddressError("friendly address CRC16 mismatch")
    workchain = payload[1] if payload[1] < 128 else payload[1] - 256
    return to_raw(workchain, payload[2:34])


def raw_to_friendly(
    raw: str, *, bounceable: bool = True, testnet: bool = False
) -> str:
    workchain, account_id = parse_raw(raw)
    tag = (BOUNCEABLE_TAG if bounceable else NON_BOUNCEABLE_TAG) | (
        TESTNET_FLAG if testnet else 0
    )
    payload = bytes([tag, workchain & 0xFF]) + account_id
    payload += crc16(payload).to_bytes(2, "big")
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def friendly_flags(address: str) -> tuple[bool, bool]:
    """(bounceable, testnet) for a friendly address."""
    try:
        payload = base64.urlsafe_b64decode(address + "=" * (-len(address) % 4))
    except Exception as exc:
        raise TonAddressError("not valid base64url") from exc
    if len(payload) != 36:
        raise TonAddressError("friendly address must decode to 36 bytes")
    tag = payload[0]
    return (tag & 0x7F) == BOUNCEABLE_TAG, bool(tag & TESTNET_FLAG)


def normalize(address: str) -> str:
    """Any accepted form → canonical raw form."""
    if ":" in address:
        workchain, account_id = parse_raw(address)
        return to_raw(workchain, account_id)
    return friendly_to_raw(address)


def is_valid(address: str, *, testnet: bool | None = None) -> bool:
    """Validate format (+ optionally the testnet flag). Masterchain
    workchain is rejected as a user destination (design §2)."""
    try:
        raw = normalize(address)
        workchain, _ = parse_raw(raw)
        if workchain == -1:
            return False
        if testnet is not None and ":" not in address:
            _bounceable, is_testnet = friendly_flags(address)
            if is_testnet != testnet:
                return False
        return True
    except TonAddressError:
        return False
