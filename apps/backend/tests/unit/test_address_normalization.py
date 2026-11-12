"""Per-chain address normalisation vectors (docs/blacklist/manual-blacklist.md §4)."""
from __future__ import annotations

import re

import pytest

from waas.common.address_normalization import normalize_address

EVM_CHECKSUM = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
EVM_LOWER = "0xdac17f958d2ee523a2206206994597c13d831ec7"
TRON_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRON_USDT_HEX = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
SOLANA_USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
TON_USDT_FRIENDLY = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"


def test_evm_lowercases_checksum_form() -> None:
    assert normalize_address("evm", EVM_CHECKSUM) == EVM_LOWER
    assert normalize_address("evm", EVM_LOWER) == EVM_LOWER


@pytest.mark.parametrize("bad", ["0x123", "dac17f958d2ee523a2206206994597c13d831ec7", "", "0xZZ"])
def test_evm_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_address("evm", bad)


def test_tron_base58check_to_canonical_hex() -> None:
    assert normalize_address("tron", TRON_USDT) == TRON_USDT_HEX
    # Hex forms (with or without the 0x41 prefix) normalise identically.
    assert normalize_address("tron", "0x" + TRON_USDT_HEX) == TRON_USDT_HEX
    assert normalize_address("tron", TRON_USDT_HEX[2:]) == TRON_USDT_HEX


def test_tron_rejects_bad_checksum() -> None:
    with pytest.raises(ValueError):
        normalize_address("tron", TRON_USDT[:-1] + "8")


def test_solana_case_sensitive_passthrough() -> None:
    assert normalize_address("solana", SOLANA_USDT) == SOLANA_USDT
    with pytest.raises(ValueError):
        normalize_address("solana", "abc")


def test_ton_friendly_to_raw_and_idempotent() -> None:
    raw = normalize_address("ton", TON_USDT_FRIENDLY)
    assert re.fullmatch(r"0:[0-9a-f]{64}", raw), raw
    assert normalize_address("ton", raw) == raw


def test_ton_bounceable_and_non_bounceable_forms_match() -> None:
    import base64

    from waas.common.address_normalization import _crc16_xmodem

    decoded = bytearray(base64.urlsafe_b64decode(TON_USDT_FRIENDLY))
    assert decoded[0] == 0x11  # bounceable tag
    decoded[0] = 0x51  # non-bounceable tag, same workchain + account hash
    decoded[34:36] = _crc16_xmodem(bytes(decoded[:34])).to_bytes(2, "big")
    non_bounceable = base64.urlsafe_b64encode(bytes(decoded)).decode().rstrip("=")
    assert normalize_address("ton", non_bounceable) == normalize_address("ton", TON_USDT_FRIENDLY)


def test_ton_rejects_bad_crc() -> None:
    with pytest.raises(ValueError):
        normalize_address("ton", TON_USDT_FRIENDLY[:-2] + "AA")


def test_unknown_family_and_empty() -> None:
    with pytest.raises(ValueError):
        normalize_address("bitcoin", EVM_LOWER)
    with pytest.raises(ValueError):
        normalize_address("evm", "   ")
